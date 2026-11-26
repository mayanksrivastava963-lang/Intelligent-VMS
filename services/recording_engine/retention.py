"""Prune completed RTSP recordings without touching active camera runs."""

import logging
import shutil
import signal
import time
from pathlib import Path
from threading import Event

from sqlalchemy import delete, select

from backend.app.core.config import load_settings
from backend.app.database.session import create_database
from backend.app.models.recordings import segments, videos


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


def retention_cycle(engine, settings):
    storage = settings["storage"].resolve()
    active = active_runs(storage)
    cutoff = time.time() - settings["retention_days"] * 86400
    low = settings["min_free_bytes"]
    high = settings["retention_free_high_bytes"]
    with engine.connect() as connection:
        rows = connection.execute(
            select(videos.c.id, videos.c.created_at, segments.c.relative_path)
            .join(segments, videos.c.id == segments.c.video_id)
            .where(videos.c.status == "ready", segments.c.relative_path.like("rtsp/%"))
            .order_by(videos.c.created_at)
        ).mappings().all()
    removed = 0
    free = shutil.disk_usage(storage).free
    clearing_space = free < low
    for row in rows:
        if row["created_at"] >= cutoff and not clearing_space:
            break
        path = (storage / row["relative_path"]).resolve()
        if not path.is_relative_to(storage / "rtsp") or path.parent in active:
            continue
        if row["created_at"] >= cutoff and free >= high:
            break
        with engine.begin() as connection:
            connection.execute(delete(videos).where(videos.c.id == row["id"], videos.c.status == "ready"))
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove retired RTSP segment")
        removed += 1
        free = shutil.disk_usage(storage).free
    # A file may outlive its metadata if a process ended during a DB outage.
    known = {row["relative_path"] for row in rows}
    root = storage / "rtsp"
    if root.exists():
        for path in root.glob("*/*/segment-*.mp4"):
            if path.parent.resolve() in active:
                continue
            try:
                if path.relative_to(storage).as_posix() not in known and time.time() - path.stat().st_mtime > 86400:
                    path.unlink()
            except OSError:
                logger.warning("Could not remove an orphaned RTSP segment")
    return removed


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    engine = create_database(settings["database_url"])
    stopping = Event()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    try:
        while not stopping.is_set():
            try:
                removed = retention_cycle(engine, settings)
                if removed:
                    logger.info("Pruned %s completed RTSP recordings", removed)
            except Exception as error:
                logger.error("Retention cycle failed (%s)", type(error).__name__)
            stopping.wait(3600)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
