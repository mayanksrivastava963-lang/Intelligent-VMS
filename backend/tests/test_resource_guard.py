import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.app.services.resource_guard import ResourceGuard, pressure_level
from backend.tests.test_product_boundary import product
from services.recording_engine import rtsp_recorder


@pytest.mark.parametrize("value,expected", [(74.9,"normal"),(75,"warn"),(79.9,"warn"),(80,"reduce"),(84.9,"reduce"),(85,"block")])
def test_threshold_boundaries(value, expected):
    assert pressure_level({"ram": value, "gpu": None}) == expected


def test_production_thresholds_are_configurable():
    assert pressure_level({"ram": 85}, (88, 92, 95)) == "normal"
    assert pressure_level({"network": 95}, (88, 92, 95)) == "block"


def test_camera_admission_is_bounded_but_existing_camera_can_recover(product):
    from backend.app.services.rtsp import admit_rtsp_camera
    headers = {"X-VMS-Request":"1"}
    ids = [product.post("/api/cameras/rtsp",json={"name":str(i),"url":"rtsp://192.168.50.10/live"},headers=headers).json()["id"] for i in range(2)]
    assert admit_rtsp_camera(product.app.state.engine,ids[0],1)
    assert not admit_rtsp_camera(product.app.state.engine,ids[1],1)
    assert admit_rtsp_camera(product.app.state.engine,ids[0],1)


def test_missing_host_telemetry_blocks_new_work(tmp_path):
    guard = ResourceGuard(dict(storage=tmp_path, resource_host_file=str(tmp_path / "missing.json")))
    snapshot = guard.snapshot()
    assert snapshot["host_telemetry_stale"]
    assert not snapshot["admit_new"] and not snapshot["optional_processing"]


def test_required_unconfigured_network_is_not_assumed_safe(tmp_path):
    snapshot = ResourceGuard(dict(storage=tmp_path, resource_required_metrics=["network"])).snapshot()
    assert snapshot["metrics"]["network"] is None
    assert snapshot["missing_required"] == ["network"]
    assert not snapshot["admit_new"]


def test_api_pressure_denies_new_start_but_keeps_existing_recording(product):
    from backend.app.services.rtsp import update_rtsp_camera, get_rtsp_camera
    headers = {"X-VMS-Request": "1"}
    camera = product.post("/api/cameras/rtsp", json={"name":"Gate", "url":"rtsp://192.168.50.10/live"}, headers=headers).json()
    product.app.state.resource_guard = SimpleNamespace(snapshot=lambda: {"admit_new":False,"optional_processing":False,"level":"block"})
    product.app.state.stream_hub = SimpleNamespace(start=lambda _:None,stop=lambda _:None,status=lambda _:"online",close=lambda:None)
    assert product.post(f"/api/cameras/{camera['id']}/start", headers=headers).status_code == 503
    assert get_rtsp_camera(product.app.state.engine,camera["id"])["status"] == "stopped"
    update_rtsp_camera(product.app.state.engine,camera["id"],"running")
    assert product.post(f"/api/cameras/{camera['id']}/start", headers=headers).status_code == 200
    assert get_rtsp_camera(product.app.state.engine,camera["id"])["status"] == "running"
    assert product.get("/api/resource-status").json()["level"] == "block"


def test_pressure_does_not_stop_existing_recorder(monkeypatch, tmp_path):
    class Stop:
        cycles = 0
        def is_set(self): return self.cycles >= 2
        def wait(self, _): self.cycles += 1
    stopping = Stop()
    monkeypatch.setattr(rtsp_recorder, "ResourceGuard", lambda _:SimpleNamespace(snapshot=lambda:{"admit_new":False}))
    monkeypatch.setattr(rtsp_recorder, "running_cameras", lambda _: {"existing"})
    monkeypatch.setattr(rtsp_recorder, "recover_completed_segments", lambda *args:None)
    monkeypatch.setattr(rtsp_recorder, "publish_completed", lambda *args:None)
    state = dict(process=SimpleNamespace(poll=lambda:None),marker=Mock(),run_dir=tmp_path,
                 last_frame=time.time(),started_at=time.time(),health_dirty=False)
    start = Mock(return_value=state)
    monkeypatch.setattr(rtsp_recorder,"start_recorder",start)
    stopped_at = []
    monkeypatch.setattr(rtsp_recorder,"stop_recorder",lambda *args:stopped_at.append(stopping.cycles))
    rtsp_recorder.supervise(None,dict(storage=tmp_path,min_free_bytes=0),stopping)
    assert start.call_count == 1  # Previously running camera is recovered despite pressure.
    assert stopped_at == [2]  # Only normal supervisor shutdown, never pressure shedding.
