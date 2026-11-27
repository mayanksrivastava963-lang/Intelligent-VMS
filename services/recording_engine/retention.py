"""Prune completed RTSP recordings without touching active or protected footage."""

import argparse
import logging
import os
import shutil
import signal
import tempfile
import time
from pathlib import Path
from threading import Event

from sqlalchemy import delete, or_, select

from backend.app.core.config import load_settings
from backend.app.database.session import create_database
from backend.app.models.recordings import segments, videos
from backend.app.services.users import add_audit


logger = logging.getLogger(__name__)


def active_runs(storage):
    result = set()
    root = storage / "rtsp"
    if not root.exists():
        return result
    now = time.time()
    for marker in root.glob("*/*/active"):
        try:
            if now - marker.stat().st_mtime < 60:
                result.add(marker.parent.resolve())
        except OSError:
            pass
    return result


def cleanup_empty_run_dirs(storage, active):
    root = storage / "rtsp"
    if not root.exists():
        return
    for run_dir in root.glob("*/*"):
        if not run_dir.is_dir():
            continue
        resolved = run_dir.resolve()
        if resolved in active or (run_dir / "active").exists():
            continue
        try:
            if not any(run_dir.iterdir()):
                run_dir.rmdir()
        except OSError:
            pass


def _record_audit(engine, action, outcome):
    try:
        with engine.begin() as connection:
            add_audit(connection, action, outcome=outcome)
    except Exception:
        logger.warning("Could not persist retention audit event (%s)", action)


def retention_cycle(engine, settings, dry_run=False):
    storage = settings["storage"].resolve()
    rtsp_root = (storage / "rtsp").resolve()
    active = active_runs(storage)
    cutoff = time.time() - settings["retention_days"] * 86400
    low = settings["min_free_bytes"]
    high = settings["retention_free_high_bytes"]
    with engine.connect() as connection:
        rows = connection.execute(
            select(videos.c.id, videos.c.created_at, videos.c.protected, segments.c.relative_path)
            .join(segments, videos.c.id == segments.c.video_id)
            .where(
                videos.c.status == "ready",
                or_(videos.c.protected.is_(False), videos.c.protected.is_(None)),
                segments.c.relative_path.like("rtsp/%"),
            )
            .order_by(videos.c.created_at)
        ).mappings().all()

    free = shutil.disk_usage(storage).free
    if low > 0 and free < low * 2:
        free_gb = free / (1024 ** 3)
        low_gb = low / (1024 ** 3)
        logger.warning("Low disk space: %.1f GB free, minimum threshold %.1f GB", free_gb, low_gb)
    if low > 0 and free < low:
        _record_audit(engine, "storage_low_disk_warning", f"free_bytes_{free}")

    clearing_space = low > 0 and free < low
    candidates = []
    protected_skipped = 0
    for row in rows:
        if row.get("protected"):
            protected_skipped += 1
            continue
        if row["created_at"] >= cutoff and not clearing_space:
            break
        path = (storage / row["relative_path"]).resolve()
        if not path.is_relative_to(rtsp_root) or path.parent in active:
            continue
        if row["created_at"] >= cutoff and free >= high:
            break
        try:
            size = path.stat().st_size if path.exists() else 0
        except OSError:
            size = 0
        candidates.append((row["id"], path, row["created_at"], size))
        free += size

    if candidates:
        oldest_date = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(candidates[0][2]))
        if dry_run:
            total_mb = sum(size for _vid, _path, _created, size in candidates) / (1024 * 1024)
            for _vid, path, _created, size in candidates:
                logger.info("Dry run: would remove %s (%.1f MB)", path, size / (1024 * 1024))
            logger.info(
                "Dry run: would remove %d recordings (oldest: %s, ~%.1f MB)",
                len(candidates), oldest_date, total_mb,
            )
            return len(candidates)

        # Remove filesystem segment first; only drop metadata for files successfully unlinked
        # or already absent on disk so a transient unlink failure does not leak orphan files.
        removed_ids = []
        removed_bytes = 0
        unlink_errors = 0
        for video_id, path, _created, size in candidates:
            try:
                path.unlink(missing_ok=True)
                removed_ids.append(video_id)
                removed_bytes += size
            except OSError:
                unlink_errors += 1
                logger.warning("Could not remove retired RTSP segment for video %s", video_id)

        if removed_ids:
            with engine.begin() as connection:
                connection.execute(
                    delete(videos).where(
                        videos.c.id.in_(removed_ids),
                        videos.c.status == "ready",
                        or_(videos.c.protected.is_(False), videos.c.protected.is_(None)),
                    )
                )
            add_args_outcome = f"removed_{len(removed_ids)}_errors_{unlink_errors}"
            _record_audit(engine, "storage_retention_cleanup", add_args_outcome)
            logger.info(
                "Retained: removed %d recordings (oldest: %s, freed ~%.1f MB)",
                len(removed_ids), oldest_date, removed_bytes / (1024 * 1024),
            )
        if not dry_run:
            cleanup_empty_run_dirs(storage, active)
        return len(removed_ids)

    # Unindexed files can be recoverable footage after a database outage.
    # Preserve them for recorder reconciliation; age alone is not deletion authority.
    if not dry_run:
        cleanup_empty_run_dirs(storage, active)
    return 0


def touch_heartbeat():
    Path(tempfile.gettempdir(), "vms-retention.heartbeat").touch()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Prune completed RTSP recordings.")
    parser.add_argument("--dry-run", action="store_true", help="Log eligible deletions without removing files or rows")
    parser.add_argument("--once", action="store_true", help="Run a single retention cycle and exit")
    args = parser.parse_args()

    settings = load_settings()
    engine = create_database(settings["database_url"])
    stopping = Event()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    cycle_seconds = settings.get("retention_cycle_seconds", 3600)
    try:
        while not stopping.is_set():
            try:
                removed = retention_cycle(engine, settings, dry_run=args.dry_run)
                if removed and not args.dry_run:
                    logger.info("Pruned %s completed RTSP recordings", removed)
            except Exception as error:
                logger.error("Retention cycle failed (%s)", type(error).__name__)
                _record_audit(engine, "storage_retention_failed", type(error).__name__)
            touch_heartbeat()
            if args.dry_run or args.once:
                break
            waited = 0
            while waited < cycle_seconds and not stopping.is_set():
                step = min(30, cycle_seconds - waited)
                stopping.wait(step)
                waited += step
                touch_heartbeat()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
