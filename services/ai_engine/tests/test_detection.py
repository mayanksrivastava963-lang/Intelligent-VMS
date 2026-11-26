from threading import Lock
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
import torch

from services.ai_engine import main as runner
from services.ai_engine.detection import detector as module
from services.ai_engine.tracking.tracker import create_tracker


@pytest.mark.parametrize("frame", [None, [], np.zeros((0, 2, 3), np.uint8),
                                  np.zeros((2, 2), np.uint8), np.zeros((2, 2, 3))])
def test_invalid_frame(frame):
    with pytest.raises(ValueError):
        module.detect_objects(frame)


@pytest.mark.parametrize("threshold", [-1, 2, float("nan"), float("inf")])
def test_invalid_threshold(threshold):
    with pytest.raises(ValueError):
        module.ObjectDetector(threshold)


def test_explicit_cuda_does_not_silently_fallback(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="unavailable"):
        module.ObjectDetector(device="cuda")


def test_filter_clamp_and_bgr_conversion():
    detector = module.ObjectDetector.__new__(module.ObjectDetector)
    detector.device = torch.device("cpu")
    detector.confidence_threshold = 0.5
    detector.categories = ["background", "person", "dog"]
    detector.target_objects = {"person"}
    detector._lock = Lock()
    colors = []

    def transform(image):
        colors.append(image.getpixel((0, 0)))
        return torch.zeros(3, 10, 20)

    detector.transform = transform
    detector.model = Mock(return_value=[{
        "boxes": torch.tensor([[-1, -2, 30, 20], [1, 1, 5, 5], [1, 1, 4, 4],
                               [8, 8, 2, 2], [0, 0, float("nan"), 4]]),
        "labels": torch.tensor([1, 2, 1, 1, 1]),
        "scores": torch.tensor([0.8, 0.9, 0.2, 0.9, 0.9]),
    }])
    frame = np.full((10, 20, 3), [10, 20, 30], dtype=np.uint8)
    results = detector.detect(frame)
    assert colors == [(30, 20, 10)]
    assert len(results) == 1
    assert results[0]["bbox"] == [0, 0, 20, 10]
    assert results[0]["class_id"] == 1
    assert results[0]["confidence"] == pytest.approx(0.8)


def test_default_model_is_reused(monkeypatch):
    fake = Mock()
    factory = Mock(return_value=fake)
    monkeypatch.setattr(module, "_default_detector", None)
    monkeypatch.setattr(module, "ObjectDetector", factory)
    frame = np.zeros((10, 10, 3), np.uint8)
    module.detect_objects(frame)
    module.detect_objects(frame)
    factory.assert_called_once()
    assert fake.detect.call_count == 2


def test_image_headless(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.png"
    assert cv2.imwrite(str(path), np.zeros((16, 16, 3), np.uint8))
    display = Mock(side_effect=AssertionError("GUI must not open"))
    monkeypatch.setattr(cv2, "imshow", display)
    detector = Mock()
    detector.detect.return_value = []
    assert runner.process_image(str(path), detector, display=False) == []
    detector.detect.assert_called_once()


def test_image_cleanup_after_inference_failure(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.png"
    assert cv2.imwrite(str(path), np.zeros((16, 16, 3), np.uint8))
    cleanup = Mock()
    monkeypatch.setattr(cv2, "destroyAllWindows", cleanup)
    detector = Mock()
    detector.detect.side_effect = RuntimeError("test")
    with pytest.raises(RuntimeError):
        runner.process_image(str(path), detector)
    cleanup.assert_called_once()


@pytest.mark.parametrize("failure", ["open", "read", "inference", None])
def test_video_cleanup_and_sampling(tmp_path, monkeypatch, failure):
    path = tmp_path / "synthetic.avi"
    path.touch()
    capture = Mock()
    capture.isOpened.return_value = failure != "open"
    capture.get.return_value = 1000
    frame = np.zeros((10, 10, 3), np.uint8)
    capture.read.side_effect = [(False, None)] if failure == "read" else [(True, frame)] * 5 + [(False, None)]
    monkeypatch.setattr(cv2, "VideoCapture", lambda _: capture)
    detector = Mock()
    detector.detect.return_value = []
    if failure == "inference":
        detector.detect.side_effect = RuntimeError("test")
    if failure:
        with pytest.raises((RuntimeError, ValueError)):
            runner.process_video(str(path), detector, False)
    else:
        result = runner.process_video(str(path), detector, False, sample_every=2)
        assert result["frames_read"] == 5
        assert result["frames_processed"] == 3
        assert result["last_video_timestamp_seconds"] == 1.0
    capture.release.assert_called_once()


def test_invalid_source_does_not_load_model(monkeypatch):
    factory = Mock(side_effect=AssertionError("must not initialize"))
    monkeypatch.setattr(runner, "ObjectDetector", factory)
    assert runner.main(["image", "nonexistent-image.png", "--headless"]) == 1
    factory.assert_not_called()


def test_real_video_decode_and_frame_limit(tmp_path):
    path = tmp_path / "generated.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    assert writer.isOpened(), "MJPG encoder is required for this integration test"
    try:
        for value in range(10):
            writer.write(np.full((48, 64, 3), value * 20, np.uint8))
    finally:
        writer.release()
    detector = Mock()
    detector.detect.return_value = []
    result = runner.process_video(str(path), detector, False, sample_every=2, max_frames=3)
    assert result["frames_read"] == 5
    assert result["frames_processed"] == 3
    assert result["last_video_timestamp_seconds"] == pytest.approx(0.4)
    assert detector.detect.call_count == 3


def test_video_tracking_integration(tmp_path):
    path = tmp_path / "tracking.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    assert writer.isOpened()
    try:
        for _ in range(5):
            writer.write(np.zeros((48, 64, 3), np.uint8))
    finally:
        writer.release()
    detector = Mock()
    detector.detect.return_value = [{"class_id": 1, "class_name": "person",
                                    "confidence": 0.9, "bbox": [5, 5, 25, 40]}]
    result = runner.process_video(str(path), detector, False, tracker=create_tracker("test"))
    assert result["tracks_created"] == 1
    track = result["latest_tracks"][0]
    assert track["status"] == "confirmed"
    assert track["hits"] == 5
    assert track["last_seen"] == pytest.approx(0.4)


def test_tracking_rejects_stalled_decoder_clock_and_releases_capture(tmp_path, monkeypatch):
    path = tmp_path / "stalled.avi"
    path.touch()
    capture = Mock()
    capture.isOpened.return_value = True
    capture.get.return_value = 0
    capture.read.return_value = (True, np.zeros((48, 64, 3), np.uint8))
    factory = Mock(return_value=capture)
    monkeypatch.setattr(cv2, "VideoCapture", factory)
    detector = Mock()
    detector.detect.return_value = []
    with pytest.raises(ValueError, match="Timestamps must increase"):
        runner.process_video(str(path), detector, False, tracker=create_tracker("test"))
    capture.release.assert_called_once()
