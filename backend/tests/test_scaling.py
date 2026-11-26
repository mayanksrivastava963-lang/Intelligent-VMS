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
                "roles", "permissions", "role_permissions", "users", "user_sessions", "audit_logs"}
    assert expected <= set(inspector.get_table_names())
    assert "ix_rtsp_cameras_created_at" in {index["name"] for index in inspector.get_indexes("rtsp_cameras")}
    engine.dispose()


def test_rtsp_segment_publication_and_retention(tmp_path):
    storage = tmp_path / "recordings"
    run = storage / "rtsp" / str(uuid4()) / str(uuid4())
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
        assert len(connection.execute(select(videos)).all()) == 1
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
    with engine.connect() as connection:
        assert connection.execute(select(videos)).first() is None
    engine.dispose()
