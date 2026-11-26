"""RTSP camera configuration and shared browser-compatible preview frames."""

import base64
import hashlib
import io
import json
import time
from threading import Condition, Event, Lock, Thread
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
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


def list_rtsp_cameras(engine, limit=None, offset=0):
    with engine.connect() as connection:
        query = select(rtsp_cameras).order_by(rtsp_cameras.c.created_at)
        if limit is not None:
            query = query.limit(limit).offset(offset)
        rows = connection.execute(query).mappings().all()
    return [public_camera(row) for row in rows]


def public_camera(row, connection_status=None):
    if connection_status is None:
        connection_status = "stopped" if row["status"] == "stopped" else "connecting"
    return {"id": row["id"], "video_id": None, "name": row["name"],
            "location": row["location"], "source_type": "rtsp", "status": row["status"],
            "connection_status": connection_status, "filename": "RTSP camera",
            "duration_seconds": None, "segments": [],
            "has_substream": bool(row["preview_source_encrypted"])}


def create_rtsp_camera(engine, secret, name, location, url, preview_url=""):
    camera_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(rtsp_cameras.insert().values(
            id=camera_id, name=name, location=location, status="stopped",
            source_encrypted=cipher(secret).encrypt(url.encode()).decode(),
            preview_source_encrypted=(cipher(secret).encrypt(preview_url.encode()).decode()
                                      if preview_url else None),
            created_at=time.time()))
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


class CameraStream:
    """One decoder and one latest-frame buffer for all viewers of a camera."""

    def __init__(self, engine, camera_id, secret, reconnect_seconds=3):
        self.engine = engine
        self.camera_id = camera_id
        self.secret = secret
        self.reconnect_seconds = reconnect_seconds
        self.stopped = Event()
        self.changed = Condition()
        self.frame = None
        self.frame_number = 0
        self.frame_time = 0.0
        self.state = "connecting"
        self.thread = Thread(target=self.run, name=f"rtsp-{camera_id[:8]}", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopped.set()
        with self.changed:
            self.state = "stopped"
            self.changed.notify_all()
        self.thread.join(timeout=6)

    def status(self):
        with self.changed:
            if self.state == "online" and time.monotonic() - self.frame_time > 3:
                return "reconnecting"
            return self.state

    def latest(self, previous_number, timeout=1):
        with self.changed:
            self.changed.wait_for(
                lambda: self.frame_number != previous_number or self.stopped.is_set(), timeout=timeout
            )
            return self.frame_number, self.frame, self.stopped.is_set()

    def run(self):
        attempts = 0
        while not self.stopped.is_set():
            try:
                row = get_rtsp_camera(self.engine, self.camera_id)
                if not row or row["status"] != "running":
                    return
                source = cipher(self.secret).decrypt(row["source_encrypted"].encode()).decode()
                with av.open(source, options={"rtsp_transport": "tcp"}, timeout=(5, 5)) as container:
                    last_frame = 0.0
                    for frame in container.decode(video=0):
                        if self.stopped.is_set():
                            return
                        now = time.monotonic()
                        if now - last_frame < 0.1:
                            continue
                        output = io.BytesIO()
                        image = frame.to_image()
                        image.thumbnail((1280, 720))
                        image.save(output, format="JPEG", quality=75)
                        with self.changed:
                            self.frame = output.getvalue()
                            self.frame_number += 1
                            self.frame_time = now
                            self.state = "online"
                            self.changed.notify_all()
                        attempts = 0
                        last_frame = now
            except Exception:
                # Decoder exceptions can include credential-bearing URLs.
                pass
            attempts += 1
            with self.changed:
                self.frame = None
                self.state = "reconnecting" if self.frame_number else "offline"
                self.changed.notify_all()
            if self.stopped.wait(min(self.reconnect_seconds * attempts, 15)):
                return


class StreamHub:
    def __init__(self, engine, secret):
        self.engine = engine
        self.secret = secret
        self.lock = Lock()
        self.streams = {}

    def start(self, camera_id):
        with self.lock:
            stream = self.streams.get(camera_id)
            if stream and stream.thread.is_alive():
                return
            stream = CameraStream(self.engine, camera_id, self.secret)
            self.streams[camera_id] = stream
            stream.start()

    def stop(self, camera_id):
        with self.lock:
            stream = self.streams.pop(camera_id, None)
        if stream:
            stream.stop()

    def restart(self, camera_id):
        self.stop(camera_id)
        self.start(camera_id)

    def status(self, camera_id):
        with self.lock:
            stream = self.streams.get(camera_id)
        return stream.status() if stream else "connecting"

    def frames(self, camera_id, session_valid):
        with self.lock:
            stream = self.streams.get(camera_id)
        if stream is None:
            return
        previous_number = 0
        last_auth_check = 0.0
        while not stream.stopped.is_set():
            now = time.monotonic()
            if now - last_auth_check >= 2:
                if not session_valid():
                    return
                last_auth_check = now
            number, frame, stopped = stream.latest(previous_number)
            if stopped:
                return
            if number != previous_number:
                previous_number = number
                if frame is not None and stream.status() == "online":
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"

    def close(self):
        with self.lock:
            camera_ids = list(self.streams)
        for camera_id in camera_ids:
            self.stop(camera_id)


class MediaMTXHub:
    """Provision RTSP sources once; MediaMTX serves all browser viewers."""

    def __init__(self, engine, secret, api_url, api_user, api_password):
        self.engine = engine
        self.secret = secret
        self.api_url = api_url.rstrip("/")
        self.authorization = "Basic " + base64.b64encode(
            f"{api_user}:{api_password}".encode()
        ).decode()

    def request(self, method, path, data=None):
        body = None if data is None else json.dumps(data).encode()
        request = Request(
            self.api_url + path, data=body, method=method,
            headers={"Authorization": self.authorization, "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=5) as response:
                return json.load(response) if method == "GET" else None
        except HTTPError as error:
            if method == "DELETE" and error.code == 404:
                return None
            if method == "POST" and error.code == 409:
                return None
            raise RuntimeError("Media server configuration is unavailable") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise RuntimeError("Media server is unavailable") from None

    def start(self, camera_id):
        row = get_rtsp_camera(self.engine, camera_id)
        if row is None:
            raise RuntimeError("Camera not found")
        paths = [(camera_id, row["source_encrypted"])]
        if row["preview_source_encrypted"]:
            paths.append((camera_id + "-preview", row["preview_source_encrypted"]))
        for path_name, encrypted in paths:
            try:
                if self.request("GET", f"/v3/config/paths/get/{path_name}"):
                    continue
            except RuntimeError:
                pass
            source = cipher(self.secret).decrypt(encrypted.encode()).decode()
            self.request("POST", f"/v3/config/paths/add/{path_name}", {
                "source": source, "rtspTransport": "tcp", "sourceOnDemand": False,
            })

    def stop(self, camera_id):
        self.request("DELETE", f"/v3/config/paths/delete/{camera_id}")
        self.request("DELETE", f"/v3/config/paths/delete/{camera_id}-preview")

    def restart(self, camera_id):
        self.stop(camera_id)
        self.start(camera_id)

    def status(self, camera_id):
        try:
            path = self.request("GET", f"/v3/paths/get/{camera_id}")
            return "online" if path.get("ready") else "reconnecting"
        except RuntimeError:
            return "offline"

    def statuses(self, camera_ids):
        try:
            paths = self.request("GET", "/v3/paths/list?itemsPerPage=500")
        except RuntimeError:
            return {camera_id: "offline" for camera_id in camera_ids}
        ready = {item["name"]: item.get("ready", False) for item in paths.get("items", [])}
        return {camera_id: ("online" if ready.get(camera_id) else "reconnecting")
                for camera_id in camera_ids}

    def close(self):
        # Paths remain available to other API workers until explicitly stopped.
        pass
