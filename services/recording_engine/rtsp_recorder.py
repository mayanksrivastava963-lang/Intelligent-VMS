"""One supervised FFmpeg stream-copy process for each running RTSP camera."""

import logging
import shutil
import signal
import subprocess
import time
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from sqlalchemy import select, update

from backend.app.core.config import load_settings
from backend.app.database.session import create_database
from backend.app.models.recordings import rtsp_cameras, segments, videos
from services.recording_engine.probe import inspect_video


logger = logging.getLogger(__name__)


def set_health(engine, camera_id, health, frame_time=None):
    values = {"health_status": health}
    if frame_time is not None:
        values["last_frame_at"] = frame_time
    with engine.begin() as connection:
        connection.execute(update(rtsp_cameras).where(rtsp_cameras.c.id == camera_id).values(**values))


def publish_segment(engine, storage, path, segment_seconds):
    relative = path.relative_to(storage).as_posix()
    with engine.connect() as connection:
        existing = connection.execute(select(segments.c.id).where(segments.c.relative_path == relative)).first()
    if existing:
        return True
    try:
        info = inspect_video(path)
        size = path.stat().st_size
    except (OSError, ValueError):
        return False
    video_id = str(uuid4())
    duration = info["duration_seconds"]
    created = path.stat().st_mtime
    with engine.begin() as connection:
        connection.execute(videos.insert().values(
            id=video_id, filename=f"camera-{path.parents[1].name[:8]}-{path.stem}.mp4",
            status="ready", bytes=size, created_at=created, updated_at=time.time(),
            duration_seconds=duration, segment_seconds=segment_seconds, progress=100,
        ))
        connection.execute(segments.insert().values(
            id=str(uuid4()), video_id=video_id, number=0, start_seconds=0,
            end_seconds=duration, duration_seconds=duration, bytes=size,
            relative_path=relative,
        ))
    return True


def read_progress(engine, camera_id, process, state):
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
        try:
            set_health(engine, camera_id, "online", state["last_frame"])
        except Exception:
            logger.warning("Recorder heartbeat database update failed for %s", camera_id)


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
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats",
        "-rtsp_transport", "tcp", "-i", source,
        "-map", "0:v:0", "-map", "0:a?", "-c:v", "copy", "-c:a", "copy",
        "-f", "segment", "-segment_time", str(settings["segment_seconds"]),
        "-reset_timestamps", "1", "-segment_format", "mp4",
        "-progress", "pipe:1", "-stats_period", "5",
        str(run_dir / "segment-%05d.mp4"),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
    state = {"process": process, "run_dir": run_dir, "marker": marker,
             "published": set(), "last_frame": 0.0}
    Thread(target=read_progress, args=(engine, camera_id, process, state), daemon=True).start()
    set_health(engine, camera_id, "connecting")
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
    publish_completed(engine, settings, state, include_latest=True)
    state["marker"].unlink(missing_ok=True)
    set_health(engine, camera_id, "stopped")


def running_cameras(engine):
    with engine.connect() as connection:
        return set(connection.execute(
            select(rtsp_cameras.c.id).where(rtsp_cameras.c.status == "running")
        ).scalars())


def recover_completed_segments(engine, settings):
    root = settings["storage"].resolve() / "rtsp"
    if not root.exists():
        return
    for path in root.glob("*/*/segment-*.mp4"):
        marker = path.parent / "active"
        if marker.exists() and time.time() - marker.stat().st_mtime < 60:
            continue
        publish_segment(engine, settings["storage"].resolve(), path, settings["segment_seconds"])


def supervise(engine, settings, stopping):
    processes = {}
    failures = {}
    recover_completed_segments(engine, settings)
    while not stopping.is_set():
        try:
            wanted = running_cameras(engine)
            for camera_id, state in list(processes.items()):
                process = state["process"]
                state["marker"].touch()
                if camera_id not in wanted or process.poll() is not None:
                    stop_recorder(engine, settings, camera_id, state)
                    del processes[camera_id]
                    if camera_id in wanted:
                        failures[camera_id] = (failures.get(camera_id, (0, 0))[0] + 1, time.time())
                        set_health(engine, camera_id, "reconnecting")
                    continue
                if state["last_frame"] and time.time() - state["last_frame"] > 30:
                    stop_recorder(engine, settings, camera_id, state)
                    del processes[camera_id]
                    failures[camera_id] = (failures.get(camera_id, (0, 0))[0] + 1, time.time())
                    set_health(engine, camera_id, "reconnecting")
                    continue
                publish_completed(engine, settings, state)
                if state["last_frame"]:
                    failures.pop(camera_id, None)
            for camera_id in wanted - processes.keys():
                count, failed_at = failures.get(camera_id, (0, 0))
                if time.time() - failed_at < min(2 ** count, 60):
                    continue
                if shutil.disk_usage(settings["storage"]).free < settings["min_free_bytes"]:
                    set_health(engine, camera_id, "offline")
                    continue
                try:
                    processes[camera_id] = start_recorder(engine, settings, camera_id)
                except (OSError, RuntimeError):
                    failures[camera_id] = (count + 1, time.time())
                    set_health(engine, camera_id, "offline")
            stopping.wait(5)
        except Exception as error:
            logger.error("Recorder supervisor cycle failed (%s)", type(error).__name__)
            stopping.wait(5)
    for camera_id, state in processes.items():
        stop_recorder(engine, settings, camera_id, state)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    engine = create_database(settings["database_url"])
    stopping = Event()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    try:
        supervise(engine, settings, stopping)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
