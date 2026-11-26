"""RTSP camera configuration and browser-compatible MJPEG streaming."""

import base64
import hashlib
import io
import time
from urllib.parse import urlsplit
from uuid import uuid4

import av
from cryptography.fernet import Fernet
from sqlalchemy import delete, select, update

from backend.app.models.recordings import rtsp_cameras


def cipher(secret):
    key = hashlib.sha256(("vms-rtsp-v1:" + secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def valid_rtsp_url(url):
    try:
        parts = urlsplit(url)
        return (parts.scheme.lower() == "rtsp" and bool(parts.hostname)
                and not any(ord(char) < 32 for char in url)
                and (parts.port is None or 0 < parts.port < 65536))
    except ValueError:
        return False


def list_rtsp_cameras(engine):
    with engine.connect() as connection:
        rows = connection.execute(select(rtsp_cameras).order_by(rtsp_cameras.c.created_at)).mappings().all()
    return [public_camera(row) for row in rows]


def public_camera(row):
    return {"id": row["id"], "video_id": None, "name": row["name"],
            "location": row["location"], "source_type": "rtsp", "status": row["status"],
            "filename": "RTSP camera", "duration_seconds": None, "segments": []}


def create_rtsp_camera(engine, secret, name, location, url):
    camera_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(rtsp_cameras.insert().values(
            id=camera_id, name=name, location=location, status="stopped",
            source_encrypted=cipher(secret).encrypt(url.encode()).decode(), created_at=time.time()))
    return camera_id


def get_rtsp_camera(engine, camera_id):
    with engine.connect() as connection:
        return connection.execute(select(rtsp_cameras).where(rtsp_cameras.c.id == camera_id)).mappings().first()


def update_rtsp_camera(engine, camera_id, status=None):
    with engine.begin() as connection:
        if status is None:
            result = connection.execute(delete(rtsp_cameras).where(rtsp_cameras.c.id == camera_id))
        else:
            result = connection.execute(update(rtsp_cameras).where(rtsp_cameras.c.id == camera_id).values(status=status))
        return result.rowcount == 1


def mjpeg_stream(engine, camera_id, secret, session_valid=None):
    while True:
        if session_valid and not session_valid():
            return
        row = get_rtsp_camera(engine, camera_id)
        if not row or row["status"] != "running":
            return
        try:
            source = cipher(secret).decrypt(row["source_encrypted"].encode()).decode()
            with av.open(source, options={"rtsp_transport": "tcp"}, timeout=(5, 5)) as container:
                last_frame = 0.0
                last_check = 0.0
                for frame in container.decode(video=0):
                    now = time.monotonic()
                    if now - last_check >= 2:
                        if session_valid and not session_valid():
                            return
                        row = get_rtsp_camera(engine, camera_id)
                        if not row or row["status"] != "running":
                            return
                        last_check = now
                    if now - last_frame < 0.1:
                        continue
                    output = io.BytesIO()
                    image = frame.to_image()
                    image.thumbnail((1280, 720))
                    image.save(output, format="JPEG", quality=75)
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + output.getvalue() + b"\r\n"
                    last_frame = now
        except Exception:
            # Camera URLs and passwords must never appear in logs or API errors.
            pass
        # A stream can close cleanly as well as fail; avoid a tight reconnect loop.
        time.sleep(3)
