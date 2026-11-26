"""Sample enabled cameras independently and run bounded batches on one model."""

import json
import logging
import os
import signal
import time
from threading import Event, Lock, Thread
from uuid import uuid4

import av
import cv2
import numpy as np
from redis import Redis
from sqlalchemy import select

from backend.app.core.config import load_settings
from backend.app.database.session import create_database
from backend.app.models.recordings import alerts, camera_ai, rtsp_cameras
from services.ai_engine.detection.detector import ObjectDetector
from services.ai_engine.rules import intrusion, loitering, unattended_object
from services.ai_engine.tracking.tracker import create_tracker, update_tracker


logger = logging.getLogger(__name__)


def enabled_rtsp_cameras(engine):
    with engine.connect() as connection:
        rows = connection.execute(
            select(rtsp_cameras.c.id, rtsp_cameras.c.preview_source_encrypted)
            .join(camera_ai, rtsp_cameras.c.id == camera_ai.c.camera_id)
            .where(rtsp_cameras.c.status == "running", camera_ai.c.enabled == 1)
        ).mappings()
        return {row["id"]: bool(row["preview_source_encrypted"]) for row in rows}


def sample_camera(camera_id, stream_name, source_base, interval, latest, lock, stopping, reset):
    source = source_base.rstrip("/") + "/" + stream_name
    backoff = 1
    while not stopping.is_set():
        try:
            with av.open(source, options={"rtsp_transport": "tcp"}, timeout=(5, 5)) as container:
                last_sample = 0.0
                backoff = 1
                for frame in container.decode(video=0):
                    if stopping.is_set():
                        return
                    now = time.monotonic()
                    if now - last_sample < interval:
                        continue
                    image = frame.to_ndarray(format="bgr24")
                    height, width = image.shape[:2]
                    if width > 640:
                        image = cv2.resize(image, (640, round(height * 640 / width)))
                    with lock:
                        latest[camera_id] = (image, now)
                    last_sample = now
            reset.add(camera_id)
        except Exception:
            # Decoder exceptions can contain source URLs; only log the camera ID.
            logger.warning("AI sampler disconnected for camera %s", camera_id)
            reset.add(camera_id)
        stopping.wait(backoff)
        backoff = min(backoff * 2, 30)


def evaluate_rules(camera_id, tracks, now, state, settings, zones):
    events = []
    polygon = zones.get(camera_id, [])
    if polygon:
        events.extend(intrusion.evaluate(tracks, polygon, state["intrusion_seen"]))
    events.extend(loitering.evaluate(
        tracks, now, settings["loitering_threshold"],
        state["loitering_entered"], state["loitering_alerted"], polygon or None,
    ))
    events.extend(unattended_object.evaluate(
        tracks, now, settings["unattended_threshold"], settings["unattended_distance"],
        state["unattended_waiting"], state["unattended_alerted"],
    ))
    return events


def camera_state(camera_id, interval):
    return {"tracker": create_tracker(camera_id, max_missing_seconds=max(3, interval * 3), min_hits=2),
            "intrusion_seen": set(), "loitering_entered": {}, "loitering_alerted": set(),
            "unattended_waiting": {}, "unattended_alerted": set()}


def run(engine, redis, settings, stopping):
    interval = settings["ai_sample_interval_ms"] / 1000
    batch_size = settings["ai_batch_size"]
    max_cameras = settings["ai_max_cameras"]
    zones = json.loads(os.getenv("AI_INTRUSION_ZONES", "{}"))
    detector = None
    latest = {}
    lock = Lock()
    reset = set()
    samplers = {}
    states = {}
    next_refresh = 0.0
    while not stopping.is_set():
        now = time.monotonic()
        if now >= next_refresh:
            try:
                configured = enabled_rtsp_cameras(engine)
                wanted = sorted(configured)[:max_cameras]
            except Exception:
                logger.warning("AI camera configuration refresh failed")
                wanted = list(samplers)
            for camera_id in list(samplers):
                if camera_id not in wanted:
                    samplers[camera_id].set()
                    del samplers[camera_id]
                    states.pop(camera_id, None)
                    with lock:
                        latest.pop(camera_id, None)
                    redis.delete("vms:ai:" + camera_id)
            for camera_id in wanted:
                if camera_id not in samplers:
                    camera_stop = Event()
                    samplers[camera_id] = camera_stop
                    states[camera_id] = camera_state(camera_id, interval)
                    Thread(target=sample_camera, args=(
                        camera_id, camera_id + "-preview" if configured[camera_id] else camera_id,
                        settings["mediamtx_rtsp_url"], interval,
                        latest, lock, camera_stop, reset,
                    ), daemon=True).start()
            next_refresh = now + 5
        with lock:
            camera_ids = list(latest)[:batch_size]
            batch = [(camera_id, *latest.pop(camera_id)) for camera_id in camera_ids]
        if not batch:
            stopping.wait(0.1)
            continue
        try:
            if detector is None:
                detector = ObjectDetector()
            started = time.perf_counter()
            detections = detector.detect_batch([frame for _camera_id, frame, _sampled in batch])
            inference_ms = round((time.perf_counter() - started) * 1000, 1)
            for (camera_id, frame, sampled), found in zip(batch, detections):
                if camera_id in reset:
                    states[camera_id] = camera_state(camera_id, interval)
                    reset.discard(camera_id)
                state = states.get(camera_id)
                if state is None:
                    continue
                tracks = update_tracker(state["tracker"], found, sampled)
                events = evaluate_rules(camera_id, tracks, sampled, state, settings, zones)
                result = {"width": frame.shape[1], "height": frame.shape[0],
                          "detections": found, "processed_at": time.time(),
                          "inference_ms": inference_ms}
                redis.setex("vms:ai:" + camera_id, max(5, int(interval * 3)), json.dumps(result))
                if events:
                    with engine.begin() as connection:
                        for event in events:
                            connection.execute(alerts.insert().values(
                                id=str(uuid4()), camera_id=camera_id, rule=event["rule"],
                                track_id=event["track_id"], message=event["message"],
                                occurred_at=time.time(),
                            ))
        except Exception as error:
            logger.error("AI batch failed (%s)", type(error).__name__)
            detector = None
            for camera_id, *_ in batch:
                states[camera_id] = camera_state(camera_id, interval)
            stopping.wait(2)
    for camera_stop in samplers.values():
        camera_stop.set()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    if not settings["redis_url"]:
        raise RuntimeError("REDIS_URL is required for the AI worker")
    engine = create_database(settings["database_url"])
    redis = Redis.from_url(settings["redis_url"], socket_connect_timeout=2, socket_timeout=2)
    stopping = Event()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    try:
        run(engine, redis, settings, stopping)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
