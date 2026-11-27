"""Isolated tests for distributed per-camera recorder leasing, sharding, and failover."""

import time
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.app.core.config import load_settings
from backend.app.database.session import create_database
from backend.app.models.recordings import recorder_workers
from backend.app.services.rtsp import create_rtsp_camera, update_rtsp_camera
from backend.tests.test_product_boundary import product
from services.recording_engine import rtsp_recorder


def test_preferred_shard_balances_across_workers():
    cams = [str(uuid4()) for _ in range(60)]
    assignments = [rtsp_recorder.preferred_shard(cid, 4) for cid in cams]
    assert set(assignments) <= {0, 1, 2, 3}
    assert all(count > 0 for count in (assignments.count(i) for i in range(4)))


def test_shard_owner_health_and_stale_failover(tmp_path):
    engine = create_database("sqlite:///" + (tmp_path / "workers.db").as_posix())
    now = time.time()
    rtsp_recorder.upsert_worker_heartbeat(engine, "recorder-0", "distributed", 0, 2, 32, 10, "running", now)
    assert rtsp_recorder.shard_owner_healthy(engine, 0, takeover_seconds=30, now=now + 5) is True
    assert rtsp_recorder.shard_owner_healthy(engine, 0, takeover_seconds=30, now=now + 45) is False
    rtsp_recorder.upsert_worker_heartbeat(engine, "recorder-0", "distributed", 0, 2, 32, 0, "stopped", now)
    assert rtsp_recorder.shard_owner_healthy(engine, 0, takeover_seconds=30, now=now + 1) is False
    engine.dispose()


def test_distributed_recorder_per_camera_lease_prevents_duplicates(tmp_path, monkeypatch):
    engine = create_database("sqlite:///" + (tmp_path / "dist.db").as_posix())
    secret = "secret-" * 6
    c1 = create_rtsp_camera(engine, secret, "Cam 1", "North", "rtsp://192.168.50.10/1")
    c2 = create_rtsp_camera(engine, secret, "Cam 2", "South", "rtsp://192.168.50.11/1")
    update_rtsp_camera(engine, c1, "running")
    update_rtsp_camera(engine, c2, "running")

    class StopAfterTwo:
        cycles = 0
        def is_set(self): return self.cycles >= 2
        def wait(self, _): self.cycles += 1

    monkeypatch.setattr(rtsp_recorder, "ResourceGuard", lambda _: SimpleNamespace(snapshot=lambda: {"admit_new": True}))
    monkeypatch.setattr(rtsp_recorder, "recover_completed_segments", lambda *a: None)
    monkeypatch.setattr(rtsp_recorder, "publish_completed", lambda *a: None)

    released = []
    # Simulate c2 lease held by another recorder worker; c1 lease acquired here.
    monkeypatch.setattr(rtsp_recorder, "acquire_camera_lease", lambda _e, cid: f"lease-{cid}" if cid == c1 else None)
    monkeypatch.setattr(rtsp_recorder, "verify_lease_alive", lambda _lease: True)
    monkeypatch.setattr(rtsp_recorder, "release_camera_lease", lambda lease, cid: released.append((lease, cid)))

    started = []
    stopped = []
    monkeypatch.setattr(rtsp_recorder, "start_recorder", lambda _e, _s, cid: (
        started.append(cid) or {"process": SimpleNamespace(poll=lambda: None), "marker": Mock(),
                                "run_dir": tmp_path, "last_frame": time.time(),
                                "started_at": time.time(), "health_dirty": False}
    ))
    monkeypatch.setattr(rtsp_recorder, "stop_recorder", lambda _e, _s, cid, _st: stopped.append(cid))

    settings = {
        "storage": tmp_path,
        "min_free_bytes": 0,
        "max_recorders": 16,
        "recorder_id": "recorder-test",
        "recorder_mode": "distributed",
        "recorder_shard_index": 0,
        "recorder_shard_total": 1,
        "recorder_takeover_seconds": 30,
    }
    rtsp_recorder.supervise(engine, settings, StopAfterTwo())
    assert started == [c1]
    assert stopped == [c1]
    assert (f"lease-{c1}", c1) in released
    with engine.connect() as conn:
        worker = conn.execute(select(recorder_workers).where(recorder_workers.c.id == "recorder-test")).mappings().one()
        assert worker["status"] == "stopped"
        assert worker["active_recorders"] == 0
    engine.dispose()


def test_distributed_mode_stops_camera_if_lease_dropped(tmp_path, monkeypatch):
    engine = create_database("sqlite:///" + (tmp_path / "lease.db").as_posix())
    secret = "secret-" * 6
    c1 = create_rtsp_camera(engine, secret, "Cam 1", "", "rtsp://192.168.50.10/1")
    update_rtsp_camera(engine, c1, "running")

    class StopAfterTwo:
        cycles = 0
        def is_set(self): return self.cycles >= 2
        def wait(self, _): self.cycles += 1

    monkeypatch.setattr(rtsp_recorder, "ResourceGuard", lambda _: SimpleNamespace(snapshot=lambda: {"admit_new": True}))
    monkeypatch.setattr(rtsp_recorder, "recover_completed_segments", lambda *a: None)
    monkeypatch.setattr(rtsp_recorder, "publish_completed", lambda *a: None)
    monkeypatch.setattr(rtsp_recorder, "acquire_camera_lease", lambda _e, cid: f"lease-{cid}")
    # First verify check fails immediately in next cycle (simulating dropped PG session).
    monkeypatch.setattr(rtsp_recorder, "verify_lease_alive", lambda _lease: False)

    stopped = []
    monkeypatch.setattr(rtsp_recorder, "start_recorder", lambda _e, _s, _cid: {
        "process": SimpleNamespace(poll=lambda: None), "marker": Mock(),
        "run_dir": tmp_path, "last_frame": time.time(),
        "started_at": time.time(), "health_dirty": False,
    })
    monkeypatch.setattr(rtsp_recorder, "stop_recorder", lambda _e, _s, cid, _st: stopped.append(cid))
    settings = {
        "storage": tmp_path,
        "min_free_bytes": 0,
        "max_recorders": 16,
        "recorder_id": "recorder-drop",
        "recorder_mode": "distributed",
        "recorder_shard_index": 0,
        "recorder_shard_total": 1,
        "recorder_takeover_seconds": 30,
    }
    rtsp_recorder.supervise(engine, settings, StopAfterTwo())
    assert c1 in stopped
    engine.dispose()


def test_metrics_and_recorder_config_validation(product, tmp_path, monkeypatch):
    res = product.get("/api/system/metrics")
    assert res.status_code == 200
    assert "recorder_workers" in res.json()
    assert product.get("/api/version").json()["version"]

    monkeypatch.setenv("RECORDING_STORAGE_PATH", str(tmp_path / "rec"))
    monkeypatch.setenv("VMS_OPERATOR_PASSWORD", "test-operator-password")
    monkeypatch.setenv("VMS_SESSION_SECRET", "test-secret-" * 5)
    monkeypatch.setenv("VMS_RECORDER_MODE", "invalid")
    with pytest.raises(RuntimeError, match="VMS_RECORDER_MODE"):
        load_settings()


def test_ai_availability_detects_live_redis_heartbeat(product):
    class FakeRedis:
        def __init__(self, alive=True):
            self.alive = alive

        def get(self, key):
            if key == "vms:ai:worker:heartbeat":
                return b'{"ts": 1}' if self.alive else None
            return None

    fake = FakeRedis(alive=True)
    product.app.state.ai_results = fake
    product.app.state.resource_guard = SimpleNamespace(
        snapshot=lambda: {"admit_new": True, "optional_processing": True, "level": "normal"}
    )
    headers = {"X-VMS-Request": "1"}
    cam = product.post("/api/cameras/rtsp", json={"name": "AI Gate", "url": "rtsp://192.168.50.10/live"}, headers=headers).json()
    assert product.get("/api/cameras").json()[0]["ai_available"] is True
    assert product.put(f"/api/cameras/{cam['id']}/ai", json={"enabled": True}, headers=headers).status_code == 200
    assert product.get(f"/api/cameras/{cam['id']}/ai/detections").json()["worker_online"] is True
    fake.alive = False
    assert product.get("/api/cameras").json()[0]["ai_available"] is False
    # Verify resource pressure cleanly blocks enabling AI with 503
    product.app.state.resource_guard = SimpleNamespace(
        snapshot=lambda: {"admit_new": False, "optional_processing": False, "level": "block"}
    )
    fake.alive = True
    assert product.put(f"/api/cameras/{cam['id']}/ai", json={"enabled": True}, headers=headers).status_code == 503
