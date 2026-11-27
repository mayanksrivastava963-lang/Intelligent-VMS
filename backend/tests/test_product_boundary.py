"""Production boundary checks use isolated SQLite data, never company footage."""

import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.main import create_app
from backend.app.models.recordings import cameras, videos
from backend.app.services.rtsp import allowed_camera_url, public_camera
from services.recording_engine.rtsp_recorder import recorder_stalled


@pytest.fixture
def product(tmp_path):
    storage = tmp_path / "recordings"
    storage.mkdir()
    settings = dict(storage=storage, database_url="sqlite:///" + (tmp_path / "product.db").as_posix(),
                    operator_username="admin", operator_password="test-product-password",
                    session_secret="test-only-product-secret-" * 3, secure_cookie=False,
                    max_upload_bytes=1000, segment_seconds=1800, min_free_bytes=0,
                    camera_networks=["192.168.50.0/24"])
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/auth/login", json={"username": "admin", "password": "test-product-password"},
                           headers={"X-VMS-Request": "1"}).status_code == 200
        yield client


def test_production_has_no_ingestion_or_simulation_routes(product):
    routes = {(route.path, method) for route in product.app.routes for method in getattr(route, "methods", [])}
    for path in ("/api/videos", "/api/videos/{video_id}/retry", "/api/cameras",
                 "/api/cameras/{camera_id}/ai/detections"):
        assert (path, "POST") not in routes
    assert product.get("/docs").status_code == 404
    assert product.get("/openapi.json").status_code == 404


def test_legacy_footage_preserved_without_virtual_controls(product):
    video_id, camera_id = str(uuid4()), str(uuid4())
    engine = product.app.state.engine
    with engine.begin() as conn:
        conn.execute(videos.insert().values(id=video_id, filename="retained.mp4", status="ready", bytes=1,
                                           created_at=time.time(), updated_at=time.time(), segment_seconds=1800))
        conn.execute(cameras.insert().values(id=camera_id, video_id=video_id, name="Old simulation",
                                            location="", status="running", created_at=time.time()))
    assert product.get("/api/cameras").json() == []
    assert product.get(f"/api/videos/{video_id}").status_code == 200
    headers = {"X-VMS-Request": "1"}
    assert product.post(f"/api/cameras/{camera_id}/start", headers=headers).status_code == 404
    assert product.delete(f"/api/cameras/{camera_id}", headers=headers).status_code == 404
    assert product.put(f"/api/cameras/{camera_id}/ai", json={"enabled": True}, headers=headers).status_code == 404
    with engine.connect() as conn:
        assert conn.execute(select(videos.c.id)).scalar_one() == video_id
        assert conn.execute(select(cameras.c.id)).scalar_one() == camera_id


@pytest.mark.parametrize("url", ["rtsp://127.0.0.1/a", "rtsp://169.254.169.254/a", "rtsp://[::1]/a",
                                     "rtsp://camera.example/a", "rtsp://192.168.51.1/a", "file:///etc/passwd"])
def test_camera_network_denials(product, url):
    response = product.post("/api/cameras/rtsp", json={"name": "Unauthorized", "url": url},
                            headers={"X-VMS-Request": "1"})
    assert response.status_code == 400
    assert url not in response.text


def test_allowed_camera_and_preview_policy(product):
    payload = {"name": "Authorized", "url": "rtsp://user:secret@192.168.50.10/live"}
    headers = {"X-VMS-Request": "1"}
    assert product.post("/api/cameras/rtsp", json={**payload, "preview_url": "rtsp://127.0.0.1/sub"}, headers=headers).status_code == 400
    response = product.post("/api/cameras/rtsp", json=payload, headers=headers)
    assert response.status_code == 201
    assert "secret" not in response.text
    assert response.json()["recording_status"] == "stopped"
    assert not allowed_camera_url(payload["url"], [])


def test_stale_recording_is_not_reported_healthy():
    row = dict(id="camera", name="Camera", location="", status="running", preview_source_encrypted=None,
               health_status="online", last_frame_at=time.time() - 60)
    assert public_camera(row)["recording_status"] == "stale"
    row["last_frame_at"] = time.time()
    assert public_camera(row)["recording_status"] == "online"


def test_recorder_timeout_includes_no_first_frame():
    assert recorder_stalled({"last_frame": 0, "started_at": 1}, now=32)
    assert not recorder_stalled({"last_frame": 0, "started_at": 1}, now=20)
    assert not recorder_stalled({"last_frame": 30, "started_at": 1}, now=32)


def test_bootstrap_config_change_cannot_create_another_administrator(product):
    from backend.app.models.users import users
    from backend.app.services.users import initialize_user_database
    engine = product.app.state.engine
    initialize_user_database(engine, "replacement-admin", "", "replacement-password")
    with engine.connect() as connection:
        assert connection.execute(select(users.c.username)).scalars().all() == ["admin"]


def test_unconfigured_ai_is_hidden_and_cannot_be_enabled(product):
    headers = {"X-VMS-Request": "1"}
    camera = product.post("/api/cameras/rtsp", json={"name": "Gate", "url": "rtsp://192.168.50.10/live"}, headers=headers).json()
    assert product.get("/api/cameras").json()[0]["ai_available"] is False
    assert product.put(f"/api/cameras/{camera['id']}/ai", json={"enabled": True}, headers=headers).status_code == 503


def test_media_reconciliation_restores_allowed_sources_and_stops_revoked_sources(product):
    from types import SimpleNamespace
    from backend.app.services.rtsp import create_rtsp_camera, update_rtsp_camera, get_rtsp_camera
    from services.recording_engine.rtsp_recorder import reconcile_sources
    engine = product.app.state.engine
    settings = product.app.state.settings
    allowed = create_rtsp_camera(engine, settings["session_secret"], "Allowed", "", "rtsp://192.168.50.10/live")
    denied = create_rtsp_camera(engine, settings["session_secret"], "Revoked", "", "rtsp://192.168.60.10/live")
    for camera_id in (allowed, denied):
        update_rtsp_camera(engine, camera_id, "running")
    started, stopped = [], []
    reconcile_sources(engine, settings, SimpleNamespace(start=started.append, stop=stopped.append))
    assert started == [allowed] and stopped == [denied]
    assert get_rtsp_camera(engine, denied)["status"] == "stopped"


def test_retention_preserves_unindexed_footage(product):
    import os
    from services.recording_engine.retention import retention_cycle

    storage = product.app.state.settings["storage"]
    path = storage / "rtsp" / str(uuid4()) / str(uuid4()) / "segment-00000.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"recoverable-company-footage")
    os.utime(path, (time.time() - 3 * 86400,) * 2)
    settings = dict(storage=storage, retention_days=1, min_free_bytes=0, retention_free_high_bytes=0)
    assert retention_cycle(product.app.state.engine, settings) == 0
    assert path.read_bytes() == b"recoverable-company-footage"
