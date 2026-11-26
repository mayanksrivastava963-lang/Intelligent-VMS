import subprocess
import time
from io import BytesIO
from fractions import Fraction
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import imageio_ffmpeg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from backend.app.main import create_app
from backend.app.models.recordings import cameras, segments, videos
from backend.app.services.recordings import claim_job, complete_job, get_video, heartbeat, recover_stale_jobs
from services.recording_engine.worker import process_job, probe_video
from services.recording_engine import worker
from services.recording_engine.probe import inspect_video


@pytest.fixture
def settings(tmp_path):
    storage = tmp_path / "recordings"
    storage.mkdir()
    return {"storage": storage, "database_url": "sqlite:///" + (tmp_path / "test.db").as_posix(),
            "operator_username": "admin", "password": "test-operator-password",
            "session_secret": "test-secret-" * 5,
            "secure_cookie": False, "max_upload_bytes": 20 * 1024**2, "min_free_bytes": 0,
            "segment_seconds": 2, "job_timeout_seconds": 120, "ffmpeg_threads": 1,
            "frontend_dist": tmp_path / "no-frontend"}


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as connection:
        yield connection


def sign_in(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "test-operator-password"}, headers={"X-VMS-Request": "1"})
    assert response.status_code == 200


def test_rtsp_camera_lifecycle_hides_credentials(client):
    from backend.app.models.recordings import rtsp_cameras

    headers = {"X-VMS-Request": "1"}
    payload = {"name": "Entrance", "location": "Lobby", "url": "rtsp://operator:secret@192.168.1.9:554/live"}
    assert client.post("/api/cameras/rtsp", json=payload, headers=headers).status_code == 401
    sign_in(client)
    assert client.post("/api/cameras/rtsp", json={**payload, "url": "file:///secret"}, headers=headers).status_code == 400
    response = client.post("/api/cameras/rtsp", json=payload, headers=headers)
    assert response.status_code == 201
    camera = response.json()
    assert camera["source_type"] == "rtsp"
    assert camera["status"] == "stopped"
    assert "secret" not in response.text
    camera_id = camera["id"]
    with client.app.state.engine.connect() as connection:
        row = connection.execute(select(rtsp_cameras).where(rtsp_cameras.c.id == camera_id)).mappings().one()
        assert "secret" not in row["source_encrypted"]
        assert "192.168.1.9" not in row["source_encrypted"]
    assert client.get(f"/api/cameras/{camera_id}/stream").status_code == 409
    assert client.post(f"/api/cameras/{camera_id}/start", headers=headers).json()["status"] == "running"
    assert "secret" not in client.get("/api/cameras").text
    assert client.post(f"/api/cameras/{camera_id}/stop", headers=headers).json()["status"] == "stopped"
    assert client.delete(f"/api/cameras/{camera_id}", headers=headers).status_code == 200
    assert client.get(f"/api/cameras/{camera_id}/stream").status_code == 404


def test_viewer_cannot_add_rtsp_camera(client):
    headers = {"X-VMS-Request": "1"}
    sign_in(client)
    response = client.post("/api/users", json={
        "full_name": "Camera Viewer", "username": "camera-viewer",
        "email": "camera-viewer@example.com", "password": "viewer-test-password",
        "role_id": "viewer",
    }, headers=headers)
    assert response.status_code == 201
    client.post("/api/auth/logout", headers=headers)
    assert client.post("/api/auth/login", json={"username": "camera-viewer", "password": "viewer-test-password"}, headers=headers).status_code == 200
    response = client.post("/api/cameras/rtsp", json={"name": "Camera", "url": "rtsp://127.0.0.1/live"}, headers=headers)
    assert response.status_code == 403


def test_rtsp_stream_shares_one_decoder_between_viewers(client, monkeypatch):
    from PIL import Image

    opened = []

    class Frame:
        def to_image(self):
            return Image.new("RGB", (32, 24), "blue")

    class Container:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def decode(self, video):
            while True:
                time.sleep(0.02)
                yield Frame()

    def open_source(*_args, **_kwargs):
        opened.append(True)
        return Container()

    monkeypatch.setattr("backend.app.services.rtsp.av.open", open_source)
    sign_in(client)
    headers = {"X-VMS-Request": "1"}
    camera = client.post("/api/cameras/rtsp", headers=headers, json={"name": "Test", "url": "rtsp://127.0.0.1/live"}).json()
    client.post(f"/api/cameras/{camera['id']}/start", headers=headers)
    hub = client.app.state.stream_hub
    first = hub.frames(camera["id"], lambda: True)
    second = hub.frames(camera["id"], lambda: True)
    first_frame = next(first)
    second_frame = next(second)
    assert first_frame.startswith(b"--frame\r\nContent-Type: image/jpeg")
    assert b"\xff\xd8\xff" in first_frame
    assert second_frame == first_frame
    assert len(opened) == 1
    listed = client.get("/api/cameras").json()
    assert next(item for item in listed if item["id"] == camera["id"])["connection_status"] == "online"
    client.post(f"/api/cameras/{camera['id']}/stop", headers=headers)
    first.close()
    second.close()


def test_rtsp_connection_failure_is_reported_without_exposing_url(client, monkeypatch):
    def fail_to_connect(*_args, **_kwargs):
        raise OSError("rtsp://operator:private@127.0.0.1/live")

    monkeypatch.setattr("backend.app.services.rtsp.av.open", fail_to_connect)
    sign_in(client)
    headers = {"X-VMS-Request": "1"}
    camera = client.post("/api/cameras/rtsp", headers=headers, json={
        "name": "Offline camera", "url": "rtsp://operator:private@127.0.0.1/live",
    }).json()
    camera_id = camera["id"]
    client.post(f"/api/cameras/{camera_id}/start", headers=headers)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        listed = client.get("/api/cameras").json()
        state = next(item for item in listed if item["id"] == camera_id)["connection_status"]
        if state == "offline":
            break
        time.sleep(0.02)
    assert state == "offline"
    assert "private" not in client.get("/api/cameras").text
    assert client.get("/api/health").status_code == 200
    client.post(f"/api/cameras/{camera_id}/stop", headers=headers)


def test_backend_exposes_swagger_and_does_not_serve_frontend(client):
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger-ui" in response.text
    assert "https://cdn.jsdelivr.net" in response.headers["content-security-policy"]
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/").status_code == 404


def test_system_metrics_are_real_cached_and_permission_protected(client):
    assert client.get("/api/system/metrics").status_code == 401
    sign_in(client)
    response = client.get("/api/system/metrics")
    assert response.status_code == 200
    metrics = response.json()
    for resource in ("cpu", "memory", "disk"):
        assert 0 <= metrics[resource]["percent"] <= 100
    assert metrics["memory"]["total_bytes"] > 0
    assert metrics["memory"]["used_bytes"] + metrics["memory"]["available_bytes"] == metrics["memory"]["total_bytes"]
    assert metrics["disk"]["total_bytes"] > 0
    assert metrics["api_memory_bytes"] > 0
    assert client.get("/api/system/metrics").json()["sampled_at"] == metrics["sampled_at"]
    headers = {"X-VMS-Request": "1"}
    assert client.post("/api/users", json={
        "full_name": "Metrics Viewer", "username": "metrics-viewer",
        "email": "metrics@example.com", "password": "viewer-test-password",
        "role_id": "viewer",
    }, headers=headers).status_code == 201
    client.post("/api/auth/logout", headers=headers)
    assert client.post("/api/auth/login", json={"username": "metrics-viewer", "password": "viewer-test-password"}, headers=headers).status_code == 200
    assert client.get("/api/system/metrics").status_code == 403


def test_system_metrics_failure_does_not_break_recordings(client, monkeypatch):
    def unavailable(_storage):
        raise OSError("Storage unavailable")

    monkeypatch.setattr("backend.app.main.read_system_metrics", unavailable)
    sign_in(client)
    response = client.get("/api/system/metrics")
    assert response.status_code == 503
    assert response.json()["detail"] == "System metrics are temporarily unavailable"
    assert client.get("/api/videos").status_code == 200


def upload(client, data, name="test.mp4"):
    return client.post("/api/videos", content=data, headers={"X-VMS-Request": "1", "X-Filename": name})


def generate_video(path, duration=5.2, fps=10, audio=True):
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-f", "lavfi",
               "-i", f"testsrc2=size=160x90:rate={fps}"]
    if audio:
        command.extend(["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"])
    command.extend(["-t", str(duration), "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p"])
    if audio:
        command.extend(["-c:a", "aac"])
    command.append(str(path))
    subprocess.run(command, check=True, timeout=60, capture_output=True)
    return path.read_bytes()


def test_probe_derives_duration_when_container_header_omits_it(monkeypatch):
    video = SimpleNamespace(
        duration=0,
        time_base=Fraction(1, 30),
        average_rate=Fraction(30, 1),
        width=1920,
        height=1080,
    )
    packets = [
        SimpleNamespace(pts=0, duration=1, time_base=Fraction(1, 30)),
        SimpleNamespace(pts=2999, duration=1, time_base=Fraction(1, 30)),
    ]

    class Container:
        duration = None
        streams = SimpleNamespace(video=[video], audio=[])

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def demux(self, _stream):
            return iter(packets)

    monkeypatch.setattr("services.recording_engine.probe.av.open", lambda *_args, **_kwargs: Container())
    result = inspect_video("missing-duration.avi")
    assert result["duration_seconds"] == pytest.approx(100 + 1 / 30)


def test_authentication_and_csrf(client):
    assert client.get("/api/videos").status_code == 401
    assert client.get("/api/segments/unknown/content").status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "test-operator-password"}).status_code == 403
    assert client.post("/api/auth/login", json={"username": "operator", "password": "test-operator-password"}, headers={"X-VMS-Request": "1"}).status_code == 401
    sign_in(client)
    session = client.get("/api/auth/session").json()
    assert session["username"] == "admin"
    assert session["role"] == "super_administrator"
    assert "user.manage" in session["permissions"]
    assert session["segment_seconds"] == 2
    assert client.post("/api/videos", content=b"x").status_code == 403
    client.post("/api/auth/logout", headers={"X-VMS-Request": "1"})
    assert client.get("/api/videos").status_code == 401
    assert client.get("/api/auth/session").status_code == 401


def test_user_management_and_role_permissions(client, settings):
    sign_in(client)
    role_response = client.get("/api/roles")
    assert role_response.status_code == 200
    assert {role["id"] for role in role_response.json()} == {
        "super_administrator", "administrator", "operator", "viewer"
    }

    created = client.post("/api/users", json={
        "full_name": "Control Room Viewer",
        "username": "viewer01",
        "email": "viewer01@example.test",
        "password": "a-secure-test-password",
        "role_id": "viewer",
    }, headers={"X-VMS-Request": "1"})
    assert created.status_code == 201
    user = created.json()
    assert user["role_id"] == "viewer"
    assert "password_hash" not in user

    viewer_settings = dict(settings)
    viewer_app = create_app(viewer_settings)
    with TestClient(viewer_app) as viewer_client:
        login = viewer_client.post("/api/auth/login", json={
            "username": "viewer01", "password": "a-secure-test-password"
        }, headers={"X-VMS-Request": "1"})
        assert login.status_code == 200
        assert viewer_client.get("/api/videos").status_code == 200
        assert viewer_client.get("/api/users").status_code == 403
        assert viewer_client.post("/api/videos", content=b"video").status_code == 403

        deactivated = client.patch(f"/api/users/{user['id']}", json={"is_active": False},
                                  headers={"X-VMS-Request": "1"})
        assert deactivated.status_code == 200
        assert viewer_client.get("/api/auth/session").status_code == 401


def test_admin_cannot_create_super_administrator(client, settings):
    sign_in(client)
    admin = client.post("/api/users", json={
        "full_name": "Regular Administrator",
        "username": "regular-admin",
        "email": "regular-admin@example.test",
        "password": "a-secure-test-password",
        "role_id": "administrator",
    }, headers={"X-VMS-Request": "1"})
    assert admin.status_code == 201
    with TestClient(create_app(dict(settings))) as regular_admin:
        login = regular_admin.post("/api/auth/login", json={
            "username": "regular-admin", "password": "a-secure-test-password"
        }, headers={"X-VMS-Request": "1"})
        assert login.status_code == 200
        response = regular_admin.post("/api/users", json={
        "full_name": "Unexpected Admin",
        "username": "unexpected-admin",
        "email": "unexpected@example.test",
        "password": "a-secure-test-password",
        "role_id": "super_administrator",
        }, headers={"X-VMS-Request": "1"})
        assert response.status_code == 403


def test_login_rate_limit(client):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}, headers={"X-VMS-Request": "1"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}, headers={"X-VMS-Request": "1"}).status_code == 429


def test_upload_validation(client, settings):
    sign_in(client)
    assert upload(client, b"x", "playlist.m3u8").status_code == 415
    assert upload(client, b"").status_code == 400
    settings["max_upload_bytes"] = 4
    assert upload(client, b"12345").status_code == 413
    assert not list(settings["storage"].rglob("source.part"))
    assert client.get("/api/videos?limit=500").status_code == 400


def test_invalid_media_is_not_published(client, settings):
    sign_in(client)
    response = upload(client, b"not video", "../../camera.mp4")
    assert response.status_code == 202
    video_id = response.json()["id"]
    assert response.json()["filename"] == "camera.mp4"
    engine = client.app.state.engine
    job = claim_job(engine)
    assert not process_job(engine, job, settings)
    result = client.get(f"/api/videos/{video_id}").json()
    assert result["status"] == "failed"
    assert result["segments"] == []
    assert not list(settings["storage"].rglob("*.mp4"))
    assert client.post(f"/api/videos/{video_id}/retry", headers={"X-VMS-Request": "1"}).status_code == 200
    assert client.post(f"/api/videos/{video_id}/retry", headers={"X-VMS-Request": "1"}).status_code == 409


def test_complete_upload_segmentation_playback(client, settings, tmp_path):
    sign_in(client)
    response = upload(client, generate_video(tmp_path / "sample.mp4"))
    assert response.status_code == 202
    video_id = response.json()["id"]
    engine = client.app.state.engine
    job = claim_job(engine)
    assert claim_job(engine) is None
    assert process_job(engine, job, settings)
    result = client.get(f"/api/videos/{video_id}").json()
    assert result["status"] == "ready"
    assert result["progress"] == 100
    assert len(result["segments"]) == 3
    assert [item["start_seconds"] for item in result["segments"]] == pytest.approx([0, 2, 4], abs=0.12)
    assert result["segments"][-1]["duration_seconds"] < 2
    with engine.connect() as connection:
        row = connection.execute(select(segments).where(segments.c.video_id == video_id)).mappings().first()
    assert probe_video(settings["storage"] / row["relative_path"])["has_audio"]
    assert "relative_path" not in result["segments"][0]
    assert "lease_token" not in result
    url = result["segments"][0]["playback_url"]
    playback = client.get(url, headers={"Range": "bytes=0-99"})
    assert playback.status_code == 206
    assert len(playback.content) == 100
    assert playback.headers["content-type"] == "video/mp4"
    assert client.get(url, headers={"Range": "bytes=0-9,20-29"}).status_code == 416


def test_two_uploaded_videos_become_independent_virtual_cameras(client, settings, tmp_path):
    sign_in(client)
    ids = []
    for name in ("entrance", "loading-bay"):
        if name == "entrance":
            source = generate_video(tmp_path / "entrance.mp4", duration=1.2, audio=False)
            filename = "entrance.mp4"
        else:
            path = tmp_path / "loading-bay.avi"
            subprocess.run([
                imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-f", "lavfi",
                "-i", "testsrc2=size=160x90:rate=10", "-t", "1.2", "-c:v", "mpeg4",
                "-q:v", "5", str(path),
            ], check=True, timeout=60, capture_output=True)
            source = path.read_bytes()
            filename = path.name
        response = upload(client, source, filename)
        assert response.status_code == 202
        ids.append(response.json()["id"])

    engine = client.app.state.engine
    for _ in ids:
        assert process_job(engine, claim_job(engine), settings)

    camera_ids = []
    for video_id, name in zip(ids, ("Entrance", "Loading bay")):
        response = client.post("/api/cameras", headers={"X-VMS-Request": "1"}, json={
            "video_id": video_id, "name": name,
        })
        assert response.status_code == 201
        camera_ids.append(response.json()["id"])
        assert client.post(f"/api/cameras/{camera_ids[-1]}/start",
                           headers={"X-VMS-Request": "1"}).status_code == 200

    listed = client.get("/api/cameras").json()
    assert {camera["id"] for camera in listed} == set(camera_ids)
    assert {camera["video_id"] for camera in listed} == set(ids)
    assert all(camera["status"] == "running" for camera in listed)
    for camera in listed:
        playback = client.get(camera["segments"][0]["playback_url"], headers={"Range": "bytes=0-99"})
        assert playback.status_code == 206
        assert playback.content.startswith(b"\x00\x00")

    assert client.post(f"/api/cameras/{camera_ids[0]}/stop",
                       headers={"X-VMS-Request": "1"}).status_code == 200
    listed = client.get("/api/cameras").json()
    assert {camera["id"]: camera["status"] for camera in listed} == {
        camera_ids[0]: "stopped", camera_ids[1]: "running",
    }


def test_actual_thirty_minute_boundaries(client, settings, tmp_path):
    settings["segment_seconds"] = 1800
    sign_in(client)
    response = upload(client, generate_video(tmp_path / "hour.mp4", duration=3605, fps=1, audio=False))
    assert response.status_code == 202
    engine = client.app.state.engine
    job = claim_job(engine)
    assert process_job(engine, job, settings)
    result = get_video(engine, job["id"])
    assert result["segment_seconds"] == 1800
    assert len(result["segments"]) == 3
    assert [item["start_seconds"] for item in result["segments"]] == pytest.approx([0, 1800, 3600], abs=0.01)
    assert [item["duration_seconds"] for item in result["segments"]] == pytest.approx([1800, 1800, 5], abs=0.01)


def test_short_video_creates_one_segment(client, settings, tmp_path):
    sign_in(client)
    upload(client, generate_video(tmp_path / "short.mp4", duration=1, audio=False))
    engine = client.app.state.engine
    job = claim_job(engine)
    assert process_job(engine, job, settings)
    assert len(get_video(engine, job["id"])["segments"]) == 1


def test_stale_job_recovery_fences_old_worker(client, settings):
    sign_in(client)
    upload(client, b"source")
    engine = client.app.state.engine
    old_job = claim_job(engine)
    with engine.begin() as connection:
        connection.execute(update(videos).values(updated_at=time.time() - 100))
    recover_stale_jobs(engine)
    new_job = claim_job(engine)
    assert old_job["id"] == new_job["id"]
    assert old_job["lease_token"] != new_job["lease_token"]
    assert not heartbeat(engine, old_job, 50, 10)
    assert heartbeat(engine, new_job, 50, 10)
    with pytest.raises(RuntimeError, match="lease lost"):
        complete_job(engine, old_job, [], 10)
    assert get_video(engine, new_job["id"])["status"] == "processing"


def test_worker_stop_does_not_publish_partial_files(client, settings, tmp_path):
    sign_in(client)
    upload(client, generate_video(tmp_path / "stop.mp4", duration=10))
    engine = client.app.state.engine
    job = claim_job(engine)
    stopping = Event()
    stopping.set()
    assert not process_job(engine, job, settings, stopping)
    assert get_video(engine, job["id"])["segments"] == []
    assert not list(settings["storage"].rglob("segment-*.mp4"))


def test_uncertain_commit_does_not_delete_published_files(client, settings, tmp_path, monkeypatch):
    sign_in(client)
    upload(client, generate_video(tmp_path / "commit.mp4", duration=1, audio=False))
    engine = client.app.state.engine
    job = claim_job(engine)

    def commit_then_disconnect(engine, job, rows, duration):
        complete_job(engine, job, rows, duration)
        raise ConnectionError("Simulated lost commit acknowledgement")

    monkeypatch.setattr(worker, "complete_job", commit_then_disconnect)
    assert not process_job(engine, job, settings)
    result = get_video(engine, job["id"])
    assert result["status"] == "ready"
    assert client.get(result["segments"][0]["playback_url"]).status_code == 200


def test_virtual_camera_lifecycle_preserves_source_recording(client):
    sign_in(client)
    engine = client.app.state.engine
    now = time.time()
    with engine.begin() as connection:
        connection.execute(videos.insert().values(
            id="ready-video", filename="entrance.mp4", status="ready", bytes=120,
            created_at=now, updated_at=now, duration_seconds=4, segment_seconds=2,
            progress=100, attempts=1,
        ))
        connection.execute(segments.insert().values(
            id="ready-segment", video_id="ready-video", number=0, start_seconds=0,
            end_seconds=4, duration_seconds=4, bytes=120,
            relative_path="ready-video/segment-0000.mp4",
        ))

    response = client.post("/api/cameras", json={
        "video_id": "ready-video", "name": "Main Entrance", "location": "North gate",
    }, headers={"X-VMS-Request": "1"})
    assert response.status_code == 201
    camera = response.json()
    assert camera["source_type"] == "virtual"
    assert camera["status"] == "stopped"
    assert camera["name"] == "Main Entrance"
    assert camera["location"] == "North gate"
    assert camera["segments"][0]["playback_url"] == "/api/segments/ready-segment/content"

    second_response = client.post("/api/cameras", json={
        "video_id": "ready-video", "name": "Loading Bay", "location": "West side",
    }, headers={"X-VMS-Request": "1"})
    assert second_response.status_code == 201
    second_camera = second_response.json()
    listed = client.get("/api/cameras").json()
    assert [item["id"] for item in listed] == [camera["id"], second_camera["id"]]
    for action, expected_status in (("start", "running"), ("restart", "running"), ("stop", "stopped")):
        result = client.post(f"/api/cameras/{camera['id']}/{action}", headers={"X-VMS-Request": "1"})
        assert result.status_code == 200
        assert result.json()["status"] == expected_status
        assert client.get("/api/cameras").json()[1]["status"] == "stopped"

    assert client.delete(f"/api/cameras/{camera['id']}", headers={"X-VMS-Request": "1"}).json() == {"deleted": True}
    assert [item["id"] for item in client.get("/api/cameras").json()] == [second_camera["id"]]
    assert client.delete(f"/api/cameras/{second_camera['id']}", headers={"X-VMS-Request": "1"}).status_code == 200
    assert client.get("/api/cameras").json() == []
    assert get_video(engine, "ready-video")["status"] == "ready"
    with engine.connect() as connection:
        assert connection.execute(select(cameras)).first() is None


def test_camera_ai_switch_and_failure_do_not_stop_video(client, monkeypatch):
    from PIL import Image

    sign_in(client)
    engine = client.app.state.engine
    now = time.time()
    with engine.begin() as connection:
        connection.execute(videos.insert().values(
            id="ai-ready-video", filename="sample.mp4", status="ready", bytes=100,
            created_at=now, updated_at=now, duration_seconds=3, segment_seconds=2,
            progress=100, attempts=1,
        ))
    headers = {"X-VMS-Request": "1"}
    camera = client.post("/api/cameras", headers=headers, json={
        "video_id": "ai-ready-video", "name": "AI camera",
    }).json()
    camera_id = camera["id"]
    assert camera["ai_enabled"] is False
    image = Image.new("RGB", (32, 24), "blue")
    output = BytesIO()
    image.save(output, format="JPEG")
    endpoint = f"/api/cameras/{camera_id}/ai/detections"
    assert client.post(endpoint, content=output.getvalue(), headers=headers).status_code == 409
    assert client.put(f"/api/cameras/{camera_id}/ai", json={"enabled": True}, headers=headers).status_code == 200
    assert client.post(f"/api/cameras/{camera_id}/start", headers=headers).json()["ai_enabled"] is True
    assert client.get("/api/cameras").json()[0]["ai_enabled"] is True
    assert client.post(endpoint, content=b"invalid-jpeg", headers=headers).status_code == 400
    client.app.state.ai_sample_times.clear()
    assert client.post(endpoint, content=b"x" * 600_001, headers=headers).status_code == 413

    def sample_detection(data):
        assert data == output.getvalue()
        return {"width": 32, "height": 24, "detections": [{
            "class_id": 1, "class_name": "person", "confidence": 0.8,
            "bbox": [1, 2, 20, 22],
        }]}

    monkeypatch.setattr("backend.app.main.detect_jpeg", sample_detection)
    result = client.post(endpoint, content=output.getvalue(), headers=headers)
    assert result.status_code == 200
    assert result.json()["detections"][0]["class_name"] == "person"
    assert client.post(endpoint, content=output.getvalue(), headers=headers).status_code == 429

    client.app.state.ai_sample_times.clear()
    monkeypatch.setattr("backend.app.main.detect_jpeg", lambda _data: (_ for _ in ()).throw(RuntimeError("GPU failed")))
    assert client.post(endpoint, content=output.getvalue(), headers=headers).status_code == 503
    assert client.get("/api/cameras").json()[0]["status"] == "running"
    assert client.put(f"/api/cameras/{camera_id}/ai", json={"enabled": False}, headers=headers).status_code == 200
    assert client.get("/api/cameras").json()[0]["ai_enabled"] is False
    assert client.post(endpoint, content=output.getvalue(), headers=headers).status_code == 409


def test_virtual_camera_requires_a_ready_recording(client):
    sign_in(client)
    response = client.post("/api/cameras", json={
        "video_id": "missing-video", "name": "Unready source",
    }, headers={"X-VMS-Request": "1"})
    assert response.status_code == 409
