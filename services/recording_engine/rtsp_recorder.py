"""One supervised FFmpeg stream-copy process for each assigned running RTSP camera."""

import logging
import os
import shutil
import signal
import subprocess
import tempfile
import time
import zlib
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError

from backend.app.core.config import load_settings
from backend.app.database.session import create_database
from backend.app.models.recordings import recorder_workers, rtsp_cameras, segments, videos
from backend.app.services.resource_guard import ResourceGuard
from backend.app.services.rtsp import MediaMTXHub, allowed_camera_url, cipher
from services.recording_engine.probe import inspect_video


logger = logging.getLogger(__name__)
GLOBAL_LOCK_ID = 1867087101
CAMERA_LOCK_NAMESPACE = 18670872


def camera_lock_objid(camera_id):
    return zlib.crc32(camera_id.encode("utf-8")) & 0x7FFFFFFF


def preferred_shard(camera_id, shard_total):
    if shard_total <= 1:
        return 0
    return zlib.crc32(camera_id.encode("utf-8")) % shard_total


def upsert_worker_heartbeat(
    engine, worker_id, mode, shard_index, shard_total, max_recorders,
    active_recorders, status="running", started_at=None,
):
    if engine is None:
        return
    now = time.time()
    started = now if started_at is None else started_at
    try:
        with engine.begin() as connection:
            updated = connection.execute(
                update(recorder_workers)
                .where(recorder_workers.c.id == worker_id)
                .values(
                    mode=mode,
                    shard_index=shard_index,
                    shard_total=shard_total,
                    max_recorders=max_recorders,
                    active_recorders=active_recorders,
                    status=status,
                    last_heartbeat_at=now,
                )
            )
            if updated.rowcount == 0:
                connection.execute(
                    recorder_workers.insert().values(
                        id=worker_id,
                        mode=mode,
                        shard_index=shard_index,
                        shard_total=shard_total,
                        max_recorders=max_recorders,
                        active_recorders=active_recorders,
                        status=status,
                        started_at=started,
                        last_heartbeat_at=now,
                    )
                )
    except SQLAlchemyError:
        logger.debug("Worker heartbeat table unavailable; continuing")


def shard_owner_healthy(engine, target_shard, takeover_seconds, now=None):
    if engine is None:
        return False
    now = time.time() if now is None else now
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                select(recorder_workers.c.last_heartbeat_at).where(
                    recorder_workers.c.status == "running",
                    recorder_workers.c.shard_index == target_shard,
                )
            ).scalars().all()
            return any(now - ts <= takeover_seconds for ts in rows)
    except SQLAlchemyError:
        return False


def acquire_camera_lease(engine, camera_id):
    """Acquire an exclusive PostgreSQL session advisory lock for one camera."""
    if engine is None or engine.dialect.name != "postgresql":
        return True
    objid = camera_lock_objid(camera_id)
    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        acquired = bool(conn.execute(
            text("SELECT pg_try_advisory_lock(:ns, :obj)"),
            {"ns": CAMERA_LOCK_NAMESPACE, "obj": objid},
        ).scalar_one())
        if not acquired:
            conn.close()
            return None
        return conn
    except Exception:
        conn.close()
        return None


def release_camera_lease(lease, camera_id):
    if lease is None or lease is True:
        return
    try:
        lease.execute(
            text("SELECT pg_advisory_unlock(:ns, :obj)"),
            {"ns": CAMERA_LOCK_NAMESPACE, "obj": camera_lock_objid(camera_id)},
        )
    except Exception:
        pass
    try:
        lease.close()
    except Exception:
        pass


def verify_lease_alive(lease):
    if lease is None or lease is True:
        return True
    try:
        lease.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def set_health(engine, camera_id, health, frame_time=None):
    values = {"health_status": health}
    if frame_time is not None:
        values["last_frame_at"] = frame_time
    with engine.begin() as connection:
        connection.execute(update(rtsp_cameras).where(rtsp_cameras.c.id == camera_id).values(**values))


def flush_health(engine, updates):
    if not updates:
        return
    with engine.begin() as connection:
        for camera_id, health, frame_time in updates:
            values = {"health_status": health}
            if frame_time is not None:
                values["last_frame_at"] = frame_time
            connection.execute(update(rtsp_cameras).where(rtsp_cameras.c.id == camera_id).values(**values))


def publish_segment(engine, storage, path, segment_seconds):
    relative = path.relative_to(storage).as_posix()
    camera_id = path.parents[1].name
    with engine.connect() as connection:
        existing = connection.execute(select(segments.c.id).where(segments.c.relative_path == relative)).first()
        if existing:
            return True
        camera_row = connection.execute(
            select(rtsp_cameras.c.name).where(rtsp_cameras.c.id == camera_id)
        ).first()
    try:
        info = inspect_video(path)
        size = path.stat().st_size
    except (OSError, ValueError):
        return False
    video_id = str(uuid4())
    duration = info["duration_seconds"]
    created = path.stat().st_mtime
    prefix = (camera_row.name.strip()[:80].replace("/", "-").replace("\\", "-")
              if camera_row and camera_row.name else f"camera-{camera_id[:8]}")
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(created))
    filename = f"{prefix}-{stamp}-{path.stem}.mp4"[:240]
    with engine.begin() as connection:
        connection.execute(videos.insert().values(
            id=video_id, filename=filename,
            status="ready", bytes=size, created_at=created, updated_at=time.time(),
            duration_seconds=duration, segment_seconds=segment_seconds, progress=100,
            camera_id=camera_id,
        ))
        connection.execute(segments.insert().values(
            id=str(uuid4()), video_id=video_id, number=0, start_seconds=0,
            end_seconds=duration, duration_seconds=duration, bytes=size,
            relative_path=relative,
        ))
    return True


def read_progress(process, state):
    last_frame = 0
    for raw_line in process.stdout:
        line = raw_line.decode(errors="ignore").strip()
        if not line.startswith("frame="):
            continue
        try:
            frame = int(line.split("=", 1)[1])
        except ValueError:
            continue
        if frame <= last_frame:
            continue
        last_frame = frame
        state["last_frame"] = time.time()
        state["health_dirty"] = True


def recorder_stalled(state, now=None):
    now = time.time() if now is None else now
    reference = state["last_frame"] or state.get("started_at", now)
    return now - reference > 30


def build_rtsp_record_command(ffmpeg, source, run_dir, segment_seconds, audio_mode="aac"):
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats",
        "-rtsp_transport", "tcp", "-rtsp_flags", "filter_src", "-i", source,
        "-map", "0:v:0",
    ]
    if audio_mode == "none":
        command.extend(["-an", "-c:v", "copy"])
    elif audio_mode == "copy":
        command.extend(["-map", "0:a?", "-c:v", "copy", "-c:a", "copy"])
    else:
        command.extend(["-map", "0:a?", "-c:v", "copy", "-c:a", "aac", "-b:a", "96k", "-ac", "2", "-ar", "48000"])
    command.extend([
        "-f", "segment", "-segment_time", str(segment_seconds),
        "-reset_timestamps", "1", "-segment_format", "mp4",
        "-segment_format_options", "movflags=+frag_keyframe+empty_moov+default_base_moof",
        "-progress", "pipe:1", "-stats_period", "5",
        str(run_dir / "segment-%05d.mp4"),
    ])
    return command


def start_recorder(engine, settings, camera_id):
    storage = settings["storage"].resolve()
    run_dir = storage / "rtsp" / camera_id / str(uuid4())
    run_dir.mkdir(parents=True, exist_ok=False)
    marker = run_dir / "active"
    marker.touch()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for RTSP recording")
    source = settings["mediamtx_rtsp_url"].rstrip("/") + "/" + camera_id
    audio_mode = os.getenv("RTSP_RECORD_AUDIO_MODE", "aac").strip().lower()
    if audio_mode not in {"aac", "copy", "none"}:
        audio_mode = "aac"
    command = build_rtsp_record_command(ffmpeg, source, run_dir, settings["segment_seconds"], audio_mode)
    # FFmpeg can emit credential-bearing URLs and unbounded stderr. Keep exit
    # codes/health in service logs instead of writing raw decoder diagnostics.
    set_health(engine, camera_id, "connecting")
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        marker.unlink(missing_ok=True)
        raise
    state = {"process": process, "run_dir": run_dir, "marker": marker,
             "published": set(), "last_frame": 0.0, "started_at": time.time(), "health_dirty": False}
    Thread(target=read_progress, args=(process, state), daemon=True).start()
    return state


def publish_completed(engine, settings, state, include_latest=False):
    files = sorted(state["run_dir"].glob("segment-*.mp4"))
    if not include_latest:
        files = files[:-1]
    for path in files:
        if path.name in state["published"]:
            continue
        if publish_segment(engine, settings["storage"].resolve(), path, settings["segment_seconds"]):
            state["published"].add(path.name)


def stop_recorder(engine, settings, camera_id, state):
    process = state["process"]
    if process.poll() is None:
        try:
            process.stdin.write(b"q\n")
            process.stdin.flush()
            process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    if state.get("errors"):
        try:
            state["errors"].close()
        except OSError:
            pass
    if process.returncode not in (0, None):
        logger.warning("Recorder exited (%s) for camera %s", process.returncode, camera_id)
    if process.stdin:
        process.stdin.close()
    publish_completed(engine, settings, state, include_latest=True)
    state["marker"].unlink(missing_ok=True)
    if state.get("error_log"):
        state["error_log"].unlink(missing_ok=True)
    set_health(engine, camera_id, "stopped")


def running_cameras(engine):
    with engine.connect() as connection:
        return set(connection.execute(
            select(rtsp_cameras.c.id).where(rtsp_cameras.c.status == "running")
        ).scalars())


def recover_completed_segments(engine, settings, active_dirs=()):
    root = settings["storage"].resolve() / "rtsp"
    if not root.exists():
        return
    for path in root.glob("*/*/segment-*.mp4"):
        if path.parent in active_dirs:
            continue
        marker = path.parent / "active"
        if marker.exists() and time.time() - marker.stat().st_mtime < 60:
            continue
        publish_segment(engine, settings["storage"].resolve(), path, settings["segment_seconds"])


def reconcile_sources(engine, settings, hub):
    """Restore persisted camera paths after media server recreation."""
    with engine.connect() as connection:
        rows = connection.execute(select(rtsp_cameras).where(rtsp_cameras.c.status == "running")).mappings().all()
    for row in rows:
        sources = [row["source_encrypted"], row["preview_source_encrypted"]]
        if all(allowed_camera_url(cipher(settings["session_secret"]).decrypt(source.encode()).decode(),
                                  settings["camera_networks"]) for source in sources if source):
            hub.start(row["id"])
        else:
            hub.stop(row["id"])
            with engine.begin() as connection:
                connection.execute(update(rtsp_cameras).where(rtsp_cameras.c.id == row["id"]).values(status="stopped"))


def supervise(engine, settings, stopping, lease=None):
    processes = {}
    camera_leases = {}
    guard = ResourceGuard(settings)
    admitted = running_cameras(engine)
    failures = {}
    recorder_id = settings.get("recorder_id", "primary")
    recorder_mode = settings.get("recorder_mode", "single")
    shard_index = settings.get("recorder_shard_index", 0)
    shard_total = settings.get("recorder_shard_total", 1)
    takeover_seconds = settings.get("recorder_takeover_seconds", 30)
    max_recorders = settings.get("max_recorders", 16)
    started_at = time.time()

    hub = (MediaMTXHub(engine, settings["session_secret"], settings["mediamtx_api_url"],
                       settings["mediamtx_api_user"], settings["mediamtx_api_password"])
           if settings.get("mediamtx_api_url") else None)
    last_recovery = 0
    last_reconcile = 0
    recover_completed_segments(engine, settings)
    while not stopping.is_set():
        try:
            if lease is not None:
                try:
                    lease.execute(text("SELECT 1"))
                except Exception:
                    # Ownership cannot be proven after losing the lock connection.
                    stopping.set()
                    break
            if hub and (recorder_mode == "single" or shard_index == 0) and time.monotonic() - last_reconcile > 15:
                try:
                    reconcile_sources(engine, settings, hub)
                except RuntimeError:
                    logger.warning("Media source reconciliation unavailable; retrying")
                last_reconcile = time.monotonic()
            wanted = running_cameras(engine)
            pressure = guard.snapshot()
            admitted.intersection_update(wanted)
            if time.monotonic() - last_recovery > 60:
                recover_completed_segments(engine, settings, {state["run_dir"] for state in processes.values()})
                last_recovery = time.monotonic()
            low_storage = shutil.disk_usage(settings["storage"]).free < settings["min_free_bytes"]
            health_batch = []
            for camera_id, state in list(processes.items()):
                process = state["process"]
                state["marker"].touch()
                lease_lost = recorder_mode == "distributed" and not verify_lease_alive(camera_leases.get(camera_id))
                if low_storage or lease_lost or camera_id not in wanted or process.poll() is not None:
                    stop_recorder(engine, settings, camera_id, state)
                    del processes[camera_id]
                    release_camera_lease(camera_leases.pop(camera_id, None), camera_id)
                    if low_storage:
                        health_batch.append((camera_id, "storage_full", None))
                    elif lease_lost:
                        logger.warning("Lost database lease for camera %s; stopped recorder", camera_id)
                        health_batch.append((camera_id, "reconnecting", None))
                    elif camera_id in wanted:
                        failures[camera_id] = (failures.get(camera_id, (0, 0))[0] + 1, time.time())
                        health_batch.append((camera_id, "reconnecting", None))
                    continue
                if recorder_stalled(state):
                    stop_recorder(engine, settings, camera_id, state)
                    del processes[camera_id]
                    release_camera_lease(camera_leases.pop(camera_id, None), camera_id)
                    failures[camera_id] = (failures.get(camera_id, (0, 0))[0] + 1, time.time())
                    health_batch.append((camera_id, "reconnecting", None))
                    continue
                if state.get("health_dirty"):
                    state["health_dirty"] = False
                    health_batch.append((camera_id, "online", state["last_frame"]))
                publish_completed(engine, settings, state)
                if state["last_frame"]:
                    failures.pop(camera_id, None)
            if health_batch:
                flush_health(engine, health_batch)
            for camera_id in sorted(wanted - processes.keys()):
                if recorder_mode == "distributed" and shard_total > 1:
                    target = preferred_shard(camera_id, shard_total)
                    if target != shard_index and shard_owner_healthy(engine, target, takeover_seconds):
                        continue
                if camera_id not in admitted and not pressure["admit_new"]:
                    set_health(engine, camera_id, "resource_limited")
                    continue
                if len(processes) >= max_recorders:
                    if recorder_mode == "single":
                        set_health(engine, camera_id, "capacity_limited")
                    continue
                count, failed_at = failures.get(camera_id, (0, 0))
                if time.time() - failed_at < min(2 ** count, 60):
                    continue
                if low_storage:
                    set_health(engine, camera_id, "storage_full")
                    continue
                cam_lease = True
                if recorder_mode == "distributed":
                    cam_lease = acquire_camera_lease(engine, camera_id)
                    if cam_lease is None:
                        continue
                try:
                    processes[camera_id] = start_recorder(engine, settings, camera_id)
                    if recorder_mode == "distributed":
                        camera_leases[camera_id] = cam_lease
                    admitted.add(camera_id)
                except (OSError, RuntimeError):
                    release_camera_lease(cam_lease, camera_id)
                    failures[camera_id] = (count + 1, time.time())
                    set_health(engine, camera_id, "offline")
            upsert_worker_heartbeat(
                engine, recorder_id, recorder_mode, shard_index, shard_total,
                max_recorders, len(processes), status="running", started_at=started_at,
            )
            (Path(tempfile.gettempdir()) / "vms-recorder.heartbeat").touch()
            stopping.wait(5)
        except Exception as error:
            logger.error("Recorder supervisor cycle failed (%s)", type(error).__name__)
            stopping.wait(5)
    for camera_id, state in processes.items():
        try:
            stop_recorder(engine, settings, camera_id, state)
        except Exception:
            logger.error("Recorder cleanup metadata unavailable for camera %s; files preserved", camera_id)
        release_camera_lease(camera_leases.pop(camera_id, None), camera_id)
    upsert_worker_heartbeat(
        engine, recorder_id, recorder_mode, shard_index, shard_total,
        max_recorders, 0, status="stopped", started_at=started_at,
    )


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    recorder_id = settings.get("recorder_id", "primary")
    recorder_mode = settings.get("recorder_mode", "single")
    logger.info("RTSP recorder '%s' starting in %s mode (shard %s/%s)",
                recorder_id, recorder_mode, settings.get("recorder_shard_index", 0), settings.get("recorder_shard_total", 1))
    engine = create_database(settings["database_url"])
    stopping = Event()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    try:
        if engine.dialect.name == "postgresql" and recorder_mode == "single":
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as lease:
                if not lease.execute(text(f"SELECT pg_try_advisory_lock({GLOBAL_LOCK_ID})")).scalar_one():
                    raise RuntimeError("Another recorder owns this database; refusing duplicate recording")
                try:
                    supervise(engine, settings, stopping, lease)
                finally:
                    lease.execute(text(f"SELECT pg_advisory_unlock({GLOBAL_LOCK_ID})"))
        else:
            supervise(engine, settings, stopping)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
