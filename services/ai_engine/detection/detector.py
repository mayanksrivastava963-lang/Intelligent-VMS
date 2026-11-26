import logging
import math
from threading import Lock

import cv2
import numpy as np
import torch
from PIL import Image
from torchvision.models.detection import (
    SSDLite320_MobileNet_V3_Large_Weights,
    ssdlite320_mobilenet_v3_large,
)


logger = logging.getLogger(__name__)
TARGET_OBJECTS = frozenset({
    "person", "backpack", "handbag", "suitcase", "car", "bus", "truck",
    "motorcycle", "bicycle",
})
_default_detector = None
_default_lock = Lock()


def validate_frame(frame):
    if not isinstance(frame, np.ndarray):
        raise ValueError("Frame must be a NumPy array")
    if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("Frame must be a uint8 BGR image with three channels")
    if frame.shape[0] == 0 or frame.shape[1] == 0:
        raise ValueError("Frame must not be empty")


class ObjectDetector:
    """One model per worker; inference accepts a bounded batch of camera frames."""

    def __init__(self, confidence_threshold=0.5, device="auto", target_objects=None):
        if not math.isfinite(confidence_threshold) or not 0 <= confidence_threshold <= 1:
            raise ValueError("Confidence threshold must be between 0 and 1")
        if device not in {"auto", "cpu", "cuda"}:
            raise ValueError("Device must be auto, cpu or cuda")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is unavailable")
        selected = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(selected if device == "auto" else device)
        self.confidence_threshold = confidence_threshold
        self.weights = SSDLite320_MobileNet_V3_Large_Weights.DEFAULT
        self.categories = self.weights.meta["categories"]
        self.target_objects = TARGET_OBJECTS if target_objects is None else frozenset(target_objects)
        if not self.target_objects or not self.target_objects.issubset(self.categories):
            raise ValueError("Target objects must contain supported model category names")
        self.transform = self.weights.transforms()
        self.model = ssdlite320_mobilenet_v3_large(weights=self.weights)
        self.model.to(self.device).eval()
        logger.info("Object detector initialized on %s", self.device)

    def detect(self, frame):
        return self.detect_batch([frame])[0]

    def detect_batch(self, frames):
        if not 1 <= len(frames) <= 8:
            raise ValueError("Inference batch must contain 1 to 8 frames")
        for frame in frames:
            validate_frame(frame)
        tensors = []
        for frame in frames:
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            tensors.append(self.transform(image).to(self.device))
        with torch.inference_mode():
            predictions = self.model(tensors)
        return [self.filter_prediction(frame, prediction)
                for frame, prediction in zip(frames, predictions)]

    def filter_prediction(self, frame, prediction):
        height, width = frame.shape[:2]
        keep = prediction["scores"] >= self.confidence_threshold
        boxes = prediction["boxes"][keep].cpu().tolist()
        labels = prediction["labels"][keep].cpu().tolist()
        scores = prediction["scores"][keep].cpu().tolist()

        detections = []
        for box, label, score in zip(boxes, labels, scores):
            if not 0 <= label < len(self.categories):
                continue
            name = self.categories[label]
            if name not in self.target_objects or not all(math.isfinite(v) for v in [*box, score]):
                continue
            x1, y1, x2, y2 = box
            box = [max(0.0, min(width, x1)), max(0.0, min(height, y1)),
                   max(0.0, min(width, x2)), max(0.0, min(height, y2))]
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            detections.append({"class_id": label, "class_name": name,
                               "confidence": float(score), "bbox": box})
        return detections


def detect_objects(frame):
    global _default_detector
    validate_frame(frame)
    with _default_lock:
        if _default_detector is None:
            _default_detector = ObjectDetector()
    return _default_detector.detect(frame)


def draw_detections(frame, detections):
    validate_frame(frame)
    for detection in detections:
        x1, y1, x2, y2 = map(int, detection["bbox"])
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        text = f"{detection['class_name']}: {detection['confidence']:.2f}"
        if "track_id" in detection:
            text = f"ID {detection['track_id']} {text} ({detection['status']})"
        cv2.putText(frame, text, (x1, max(20, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    return frame
