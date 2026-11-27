"""Isolated tests for automatic recording retention, protection, and audit logging."""

import time
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.app.core.config import load_settings
from backend.app.models.recordings import segments, videos
from backend.app.models.users import audit_logs
from backend.tests.test_product_boundary import product
from services.recording_engine.retention import retention_cycle


def _seed_rtsp_segment(engine, storage, age_days=5, size=2048, protected=False, active=False, name_prefix="seg"):
    video_id = str(uuid4())
    camera_id = str(uuid4())
    run_dir = storage / "rtsp" / camera_id / str(uuid4())
    run_dir.mkdir(parents=True, exist_ok=True)
    if active:
        (run_dir / "active").touch()
    path = run_dir / f"{name_prefix}.mp4"
    path.write_bytes(b"\x00" * size)
    created_at = time.time() - age_days * 86400
    with engine.begin() as connection:
        connection.execute(videos.insert().values(
            id=video_id,
            filename=f"{name_prefix}-{video_id[:6]}.mp4",
            status="ready",
            bytes=size,
            created_at=created_at,
            updated_at=created_at,
            duration_seconds=60.0,
            segment_seconds=1800,
            progress=100.0,
            camera_id=camera_id,
            protected=protected,
        ))
        connection.execute(segments.insert().values(
            id=str(uuid4()),
            video_id=video_id,
            number=0,
            start_seconds=0.0,
            end_seconds=60.0,
            duration_seconds=60.0,
            bytes=size,
            relative_path=path.relative_to(storage).as_posix(),
        ))
    return video_id, path


def test_dry_run_reports_candidates_without_deleting(product):
    engine = product.app.state.engine
    storage = product.app.state.settings["storage"]
    video_id, path = _seed_rtsp_segment(engine, storage, age_days=10)
    settings = {"storage": storage, "retention_days": 1, "min_free_bytes": 0, "retention_free_high_bytes": 0}
    assert retention_cycle(engine, settings, dry_run=True) == 1
    assert path.exists()
    with engine.connect() as conn:
        assert conn.execute(select(videos.c.id).where(videos.c.id == video_id)).first() is not None


def test_protected_and_active_recordings_survive_expiry_and_low_disk(product):
    engine = product.app.state.engine
    storage = product.app.state.settings["storage"]
    protected_id, protected_path = _seed_rtsp_segment(engine, storage, age_days=45, protected=True, name_prefix="prot")
    active_id, active_path = _seed_rtsp_segment(engine, storage, age_days=45, active=True, name_prefix="act")
    eligible_id, eligible_path = _seed_rtsp_segment(engine, storage, age_days=45, protected=False, name_prefix="old")

    # Force low-disk clearing mode simultaneously with extreme min_free_bytes
    settings = {
        "storage": storage,
        "retention_days": 30,
        "min_free_bytes": 10 ** 16,
        "retention_free_high_bytes": 2 * 10 ** 16,
    }
    assert retention_cycle(engine, settings) == 1
    assert not eligible_path.exists()
    assert protected_path.exists()
    assert active_path.exists()
    with engine.connect() as conn:
        remaining = set(conn.execute(select(videos.c.id)).scalars().all())
        assert remaining == {protected_id, active_id}


def test_retention_writes_cleanup_audit_log(product):
    engine = product.app.state.engine
    storage = product.app.state.settings["storage"]
    _seed_rtsp_segment(engine, storage, age_days=5)
    settings = {"storage": storage, "retention_days": 1, "min_free_bytes": 0, "retention_free_high_bytes": 0}
    assert retention_cycle(engine, settings) == 1
    with engine.connect() as conn:
        actions = conn.execute(select(audit_logs.c.action).order_by(audit_logs.c.created_at.desc())).scalars().all()
    assert "storage_retention_cleanup" in actions


def test_retention_unlink_failure_preserves_metadata_for_recovery(product, monkeypatch):
    from pathlib import Path

    engine = product.app.state.engine
    storage = product.app.state.settings["storage"]
    video_id, path = _seed_rtsp_segment(engine, storage, age_days=10)
    real_unlink = Path.unlink

    def fail_unlink(self, missing_ok=False):
        if self == path:
            raise OSError("Simulated busy file lock")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    settings = {"storage": storage, "retention_days": 1, "min_free_bytes": 0, "retention_free_high_bytes": 0}
    assert retention_cycle(engine, settings) == 0
    assert path.exists()
    with engine.connect() as conn:
        assert conn.execute(select(videos.c.id).where(videos.c.id == video_id)).first() is not None


def test_recording_protection_api_and_audit(product):
    engine = product.app.state.engine
    storage = product.app.state.settings["storage"]
    video_id, _ = _seed_rtsp_segment(engine, storage, age_days=1)
    headers = {"X-VMS-Request": "1"}
    resp = product.put(f"/api/videos/{video_id}/protection", json={"protected": True}, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"id": video_id, "protected": True}
    assert product.get(f"/api/videos/{video_id}").json()["protected"] is True
    resp = product.put(f"/api/videos/{video_id}/protection", json={"protected": False}, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"id": video_id, "protected": False}
    assert product.put("/api/videos/nonexistent/protection", json={"protected": True}, headers=headers).status_code == 404
    logs = product.get("/api/audit-logs?limit=20").json()
    actions = [item["action"] for item in logs]
    assert "recording_protected" in actions
    assert "recording_unprotected" in actions


def test_retention_cycle_seconds_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("RECORDING_STORAGE_PATH", str(tmp_path / "rec"))
    monkeypatch.setenv("VMS_OPERATOR_PASSWORD", "test-operator-password")
    monkeypatch.setenv("VMS_SESSION_SECRET", "test-secret-" * 5)
    monkeypatch.setenv("RETENTION_CYCLE_SECONDS", "15")
    with pytest.raises(RuntimeError, match="RETENTION_CYCLE_SECONDS"):
        load_settings()
