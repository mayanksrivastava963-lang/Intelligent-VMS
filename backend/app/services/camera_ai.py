"""Persist per-camera AI switches and analyze explicitly sampled JPEG frames."""

import io

from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete, select

from backend.app.models.recordings import camera_ai


class InvalidFrame(ValueError):
    pass


def enabled_camera_ids(engine):
    with engine.connect() as connection:
        rows = connection.execute(
            select(camera_ai.c.camera_id).where(camera_ai.c.enabled == 1)
        )
        return {row.camera_id for row in rows}


def is_enabled(engine, camera_id):
    with engine.connect() as connection:
        return connection.execute(
            select(camera_ai.c.enabled).where(camera_ai.c.camera_id == camera_id)
        ).scalar_one_or_none() == 1


def set_enabled(engine, camera_id, enabled):
    with engine.begin() as connection:
        connection.execute(delete(camera_ai).where(camera_ai.c.camera_id == camera_id))
        if enabled:
            connection.execute(camera_ai.insert().values(camera_id=camera_id, enabled=1))


def remove_camera_setting(engine, camera_id):
    with engine.begin() as connection:
        connection.execute(delete(camera_ai).where(camera_ai.c.camera_id == camera_id))


def detect_jpeg(frame_bytes):
    """Load the shared model only when an enabled camera sends a sample."""
    try:
        with Image.open(io.BytesIO(frame_bytes)) as image:
            if image.format != "JPEG" or image.width > 1280 or image.height > 720:
                raise InvalidFrame("Send a JPEG frame no larger than 1280x720")
            if image.width < 1 or image.height < 1:
                raise InvalidFrame("Invalid frame dimensions")
            rgb = image.convert("RGB")
    except (UnidentifiedImageError, OSError) as error:
        raise InvalidFrame("Invalid JPEG frame") from error

    import cv2
    import numpy as np
    from services.ai_engine.detection.detector import detect_objects

    bgr = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
    return {"width": rgb.width, "height": rgb.height, "detections": detect_objects(bgr)}
