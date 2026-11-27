"""Focused regression checks for the multi-camera infrastructure."""

import time
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import imageio_ffmpeg
from alembic import command
from alembic.config import Config
from sqlalchemy import event, inspect, select

from backend.app.database.session import create_database
from backend.app.main import client_address
from backend.app.models.recordings import cameras, segments, videos
from backend.app.services.login_limiter import LoginLimiter
from backend.app.services.recordings import list_cameras
from backend.app.services.rtsp import MediaMTXHub, create_rtsp_camera
from services.recording_engine.rtsp_recorder import publish_segment
from services.recording_engine.retention import retention_cycle


def test_camera_list_uses_two_selects_for_many_cameras(tmp_path):
    engine = create_database("sqlite:///" + (tmp_path / "cameras.db").as_posix())
    now = time.time()
    with engine.begin() as connection:
        for number in range(60):
            video_id = str(uuid4())
            connection.execute(videos.insert().values(
                id=video_id, filename=f"video-{number}.mp4", status="ready", bytes=100,
                created_at=now + number, updated_at=now, segment_seconds=1800,
            ))
            connection.execute(cameras.insert().values(
                id=str(uuid4()), video_id=video_id, name=f"Camera {number}",
                location="", status="running", created_at=now + number,
            ))
            connection.execute(segments.insert().values(
                id=str(uuid4()), video_id=video_id, number=0, start_seconds=0,
                end_seconds=1, duration_seconds=1, bytes=100,
                relative_path=f"{video_id}/part.mp4",
            ))
    queries = []

    def count_selects(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        result = list_cameras(engine)
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)
        engine.dispose()
    assert len(result) == 60
    assert all(len(camera["segments"]) == 1 for camera in result)
    assert len(queries) == 2


def test_mediamtx_hub_registers_encrypted_source_without_exposing_it(tmp_path):
    engine = create_database("sqlite:///" + (tmp_path / "streams.db").as_posix())
    secret = "test-secret-" * 5
    source = "rtsp://operator:private@127.0.0.1/live"
    preview = "rtsp://operator:other-private@127.0.0.1/sub"
    camera_id = create_rtsp_camera(engine, secret, "Entrance", "Lobby", source, preview)
    hub = MediaMTXHub(engine, secret, "http://mediamtx:9997", "vms-api", "test-key")
    calls = []

    def request(method, path, data=None):
        calls.append((method, path, data))
        if path.startswith("/v3/paths/list"):
            return {"items": [{"name": camera_id, "ready": True}]}

    hub.request = request
    hub.start(camera_id)
    published = [data["source"] for method, _path, data in calls if method == "POST"]
    assert published == [source, preview]
    assert hub.statuses([camera_id])[camera_id] == "online"
    hub.stop(camera_id)
    assert calls[-2][:2] == ("DELETE", f"/v3/config/paths/delete/{camera_id}")
    assert calls[-1][:2] == ("DELETE", f"/v3/config/paths/delete/{camera_id}-preview")
    engine.dispose()


def test_redis_login_limiter_is_shared_and_clears_success():
    class FakeRedis:
        def __init__(self):
            self.count = 0

        def eval(self, _script, _keys, _key):
            self.count += 1
            return self.count

        def delete(self, _key):
            self.count = 0

    redis = FakeRedis()
    limiter = LoginLimiter()
    limiter.redis = redis
    assert all(limiter.allow("127.0.0.1") for _ in range(5))
    assert not limiter.allow("127.0.0.1")
    limiter.clear("127.0.0.1")
    assert limiter.allow("127.0.0.1")


def test_client_ip_header_only_from_trusted_proxy():
    state = SimpleNamespace(settings={"trusted_proxy_cidrs": ["172.16.0.0/12"]})
    app = SimpleNamespace(state=state)
    trusted = SimpleNamespace(app=app, client=SimpleNamespace(host="172.20.0.3"),
                              headers={"x-real-ip": "198.51.100.4"})
    untrusted = SimpleNamespace(app=app, client=SimpleNamespace(host="198.51.100.5"),
                                headers={"x-real-ip": "198.51.100.4"})
    assert client_address(trusted) == "198.51.100.4"
    assert client_address(untrusted) == "198.51.100.5"


def test_baseline_migration_creates_schema(tmp_path, monkeypatch):
    database = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + database.as_posix())
    monkeypatch.setenv("RECORDING_STORAGE_PATH", str(tmp_path / "recordings"))
    monkeypatch.setenv("VMS_OPERATOR_PASSWORD", "test-operator-password")
    monkeypatch.setenv("VMS_SESSION_SECRET", "test-secret-" * 5)
    config = Config("backend/alembic.ini")
    command.upgrade(config, "head")
    engine = create_database("sqlite:///" + database.as_posix())
    inspector = inspect(engine)
    expected = {"recording_videos", "recording_segments", "cameras", "rtsp_cameras",
                "camera_ai", "alerts",
                "roles", "permissions", "role_permissions", "users", "user_sessions", "audit_logs"}
    assert expected <= set(inspector.get_table_names())
    assert "ix_rtsp_cameras_created_at" in {index["name"] for index in inspector.get_indexes("rtsp_cameras")}
    assert "ix_recording_videos_camera_id" in {index["name"] for index in inspector.get_indexes("recording_videos")}
    engine.dispose()


def test_rtsp_segment_publication_and_retention(tmp_path):
    storage = tmp_path / "recordings"
    camera_id = str(uuid4())
    run = storage / "rtsp" / camera_id / str(uuid4())
    run.mkdir(parents=True)
    path = run / "segment-00000.mp4"
    subprocess.run([
        imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10", "-t", "1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ], check=True, capture_output=True)
    engine = create_database("sqlite:///" + (tmp_path / "retention.db").as_posix())
    assert publish_segment(engine, storage, path, 1800)
    assert publish_segment(engine, storage, path, 1800)
    with engine.begin() as connection:
        rows = connection.execute(select(videos)).mappings().all()
        assert len(rows) == 1
        assert rows[0]["camera_id"] == camera_id
        connection.execute(videos.update().values(created_at=time.time() - 3 * 86400))
    settings = {"storage": storage, "retention_days": 1, "min_free_bytes": 0,
                "retention_free_high_bytes": 0}
    marker = run / "active"
    marker.touch()
    assert retention_cycle(engine, settings) == 0
    assert path.exists()
    marker.unlink()
    assert retention_cycle(engine, settings) == 1
    assert not path.exists()
    assert not run.exists()
    with engine.connect() as connection:
        assert connection.execute(select(videos)).first() is None
    engine.dispose()


def test_initialize_user_database_is_idempotent(tmp_path):
    from backend.app.core.security import hash_password
    from backend.app.models.users import users as users_table
    from backend.app.services.users import initialize_user_database

    engine = create_database("sqlite:///" + (tmp_path / "seed.db").as_posix())
    password_hash = hash_password("test-operator-password")
    initialize_user_database(engine, "admin", password_hash)
    initialize_user_database(engine, "admin", password_hash)
    with engine.connect() as connection:
        assert len(connection.execute(select(users_table)).all()) == 1
    engine.dispose()


def test_rtsp_recorder_command_batch_health_and_ai_sharding(tmp_path):
    from pathlib import Path
    from backend.app.models.recordings import rtsp_cameras
    from services.ai_engine.worker import select_shard_cameras
    from services.recording_engine.rtsp_recorder import build_rtsp_record_command, flush_health

    command = build_rtsp_record_command("ffmpeg", "rtsp://mediamtx:8554/cam1", Path("/tmp/run"), 1800)
    assert "copy" in command
    assert "aac" in command
    assert any("frag_keyframe" in arg for arg in command)

    engine = create_database("sqlite:///" + (tmp_path / "health.db").as_posix())
    cam1 = create_rtsp_camera(engine, "secret-" * 6, "Gate", "North", "rtsp://127.0.0.1/1")
    cam2 = create_rtsp_camera(engine, "secret-" * 6, "Yard", "South", "rtsp://127.0.0.1/2")
    flush_health(engine, [(cam1, "online", 100.5), (cam2, "reconnecting", None)])
    with engine.connect() as connection:
        rows = {row["id"]: row for row in connection.execute(select(rtsp_cameras)).mappings()}
        assert rows[cam1]["health_status"] == "online"
        assert rows[cam1]["last_frame_at"] == 100.5
        assert rows[cam2]["health_status"] == "reconnecting"
    engine.dispose()

    cameras_set = {"cam-a", "cam-b", "cam-c", "cam-d"}
    shard_0 = select_shard_cameras(cameras_set, 10, shard_index=0, shard_total=2)
    shard_1 = select_shard_cameras(cameras_set, 10, shard_index=1, shard_total=2)
    assert sorted(shard_0 + shard_1) == sorted(cameras_set)
    assert set(shard_0).isdisjoint(shard_1)


def test_videos_filter_and_proxy_audit_ip(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app.main import create_app

    storage = tmp_path / "recordings"
    storage.mkdir()
    settings = {
        "storage": storage, "database_url": "sqlite:///" + (tmp_path / "api.db").as_posix(),
        "operator_username": "admin", "password": "test-operator-password",
        "session_secret": "test-secret-" * 5, "secure_cookie": False,
        "max_upload_bytes": 1024 ** 2, "min_free_bytes": 0, "segment_seconds": 60,
        "job_timeout_seconds": 30, "ffmpeg_threads": 1, "frontend_dist": tmp_path / "no-dist",
        "trusted_proxy_cidrs": ["127.0.0.1/32"],
    }
    with TestClient(create_app(settings), client=("127.0.0.1", 50000)) as client:
        headers = {"X-VMS-Request": "1", "X-Real-IP": "203.0.113.42"}
        assert client.post("/api/auth/login", json={"username": "admin", "password": "test-operator-password"}, headers=headers).status_code == 200
        engine = client.app.state.engine
        now = time.time()
        with engine.begin() as connection:
            connection.execute(videos.insert().values(
                id="vid-1", filename="Gate-20261126.mp4", status="ready", bytes=100,
                created_at=now, updated_at=now, segment_seconds=60, camera_id="cam-gate",
            ))
            connection.execute(videos.insert().values(
                id="vid-2", filename="Lobby-20261126.mp4", status="ready", bytes=100,
                created_at=now + 1, updated_at=now, segment_seconds=60, camera_id="cam-lobby",
            ))
        filtered = client.get("/api/videos?camera_id=cam-gate").json()
        assert [item["id"] for item in filtered] == ["vid-1"]
        searched = client.get("/api/videos?q=lobby").json()
        assert [item["id"] for item in searched] == ["vid-2"]
        assert client.post("/api/auth/logout", headers=headers).status_code == 200
        assert client.post("/api/auth/login", json={"username": "admin", "password": "test-operator-password"}, headers=headers).status_code == 200
        logs = client.get("/api/audit-logs?limit=10").json()
        logout_events = [item for item in logs if item["action"] == "logout"]
        assert logout_events and logout_events[0]["remote_address"] == "203.0.113.42"
