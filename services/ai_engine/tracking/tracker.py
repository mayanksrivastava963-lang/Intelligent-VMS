import math
from copy import deepcopy
from uuid import uuid4

import numpy as np
from scipy.optimize import linear_sum_assignment


def create_tracker(camera_id, max_missing_seconds=2.0, min_iou=0.2,
                   min_hits=3, history_size=100, max_tracks=256):
    if not isinstance(camera_id, str) or not camera_id.strip():
        raise ValueError("camera_id must be a nonempty string")
    if not math.isfinite(max_missing_seconds) or max_missing_seconds <= 0:
        raise ValueError("max_missing_seconds must be positive and finite")
    if not math.isfinite(min_iou) or not 0 < min_iou <= 1:
        raise ValueError("min_iou must be between 0 (exclusive) and 1")
    for value in (min_hits, history_size, max_tracks):
        if type(value) is not int or value < 1:
            raise ValueError("Track limits must be positive integers")
    return {"camera_id": camera_id, "session_id": uuid4().hex,
            "max_missing_seconds": max_missing_seconds, "min_iou": min_iou,
            "min_hits": min_hits, "history_size": history_size,
            "max_tracks": max_tracks, "next_id": 1, "last_timestamp": None,
            "tracks": {}}


def reset_tracker(tracker):
    """Call on stream reconnect/seek; never bridge an unknown interruption."""
    tracker["tracks"].clear()
    tracker["last_timestamp"] = None


def validate_detections(detections, limit):
    if not isinstance(detections, list) or len(detections) > limit:
        raise ValueError("Detections must be a list within the configured track limit")
    result = []
    for detection in detections:
        if not isinstance(detection, dict):
            raise ValueError("Each detection must be a dictionary")
        label = detection.get("class_id")
        name = detection.get("class_name")
        confidence = detection.get("confidence")
        box = detection.get("bbox")
        if type(label) is not int or label < 0 or not isinstance(name, str) or not name:
            raise ValueError("Detection class ID and name are invalid")
        if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("Detection confidence must be finite and between 0 and 1")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            raise ValueError("Detection bbox must contain four XYXY coordinates")
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in box):
            raise ValueError("Detection bbox coordinates must be finite numbers")
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError("Detection bbox must have positive area")
        result.append({"class_id": label, "class_name": name,
                       "confidence": float(confidence), "bbox": list(box)})
    return result


def intersection_over_union(first, second):
    width = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    height = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    intersection = width * height
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / (first_area + second_area - intersection)


def predicted_box(track, timestamp):
    elapsed = timestamp - track["last_seen"]
    dx = track["velocity"][0] * elapsed
    dy = track["velocity"][1] * elapsed
    x1, y1, x2, y2 = track["bbox"]
    return [x1 + dx, y1 + dy, x2 + dx, y2 + dy]


def match_detections(tracks, detections, timestamp, min_iou):
    if not tracks or not detections:
        return []
    # A forbidden edge costs more than all valid edges combined.
    forbidden = len(tracks) + len(detections) + 1
    costs = np.full((len(tracks), len(detections)), float(forbidden))
    for row, track in enumerate(tracks):
        prediction = predicted_box(track, timestamp)
        for column, detection in enumerate(detections):
            if (track["class_id"], track["class_name"]) != (detection["class_id"], detection["class_name"]):
                continue
            overlap = intersection_over_union(prediction, detection["bbox"])
            if overlap >= min_iou:
                costs[row, column] = 1.0 - overlap
    rows, columns = linear_sum_assignment(costs)
    matches = []
    for row, column in zip(rows, columns):
        if costs[row, column] < forbidden:
            matches.append((int(row), int(column)))
    return matches


def record_observation(track, detection, timestamp, tracker):
    old_box = track["bbox"]
    box = detection["bbox"]
    elapsed = timestamp - track["last_seen"]
    if elapsed > 0:
        track["velocity"] = [
            ((box[0] + box[2]) - (old_box[0] + old_box[2])) / (2 * elapsed),
            ((box[1] + box[3]) - (old_box[1] + old_box[3])) / (2 * elapsed),
        ]
    track.update(detection)
    track["last_seen"] = timestamp
    track["hits"] += 1
    track["consecutive_hits"] += 1
    track["confirmed"] = track["confirmed"] or track["consecutive_hits"] >= tracker["min_hits"]
    track["observed"] = True
    track["status"] = "confirmed" if track["confirmed"] else "tentative"
    track["history"].append({"timestamp": timestamp,
                             "center": [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]})
    track["history"] = track["history"][-tracker["history_size"]:]


def update_tracker(tracker, detections, timestamp):
    """Use video seconds or live monotonic seconds; one sequential owner per camera."""
    if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp < 0:
        raise ValueError("Timestamp must be finite nonnegative seconds")
    if tracker["last_timestamp"] is not None and timestamp <= tracker["last_timestamp"]:
        raise ValueError("Timestamps must increase; reset the tracker after a seek/reconnect")
    detections = validate_detections(detections, tracker["max_tracks"])
    active = []
    for track in tracker["tracks"].values():
        if timestamp - track["last_seen"] <= tracker["max_missing_seconds"]:
            active.append(track)
    matches = match_detections(active, detections, timestamp, tracker["min_iou"])
    matched_rows = {row for row, _ in matches}
    matched_columns = {column for _, column in matches}
    required = len(active) + len(detections) - len(matches)
    if required > tracker["max_tracks"]:
        raise ValueError("Tracker capacity exceeded; increase max_tracks or reduce detections")

    for row, column in matches:
        record_observation(active[row], detections[column], timestamp, tracker)
    for row, track in enumerate(active):
        if row not in matched_rows:
            track["observed"] = False
            track["consecutive_hits"] = 0
            track["status"] = "lost"
    for column, detection in enumerate(detections):
        if column in matched_columns:
            continue
        track = {"track_id": tracker["next_id"], "camera_id": tracker["camera_id"],
                 "session_id": tracker["session_id"], "first_seen": timestamp,
                 "last_seen": timestamp, "bbox": detection["bbox"],
                 "velocity": [0.0, 0.0], "hits": 0, "consecutive_hits": 0,
                 "confirmed": False, "history": []}
        tracker["next_id"] += 1
        record_observation(track, detection, timestamp, tracker)
        active.append(track)
    tracker["tracks"] = {track["track_id"]: track for track in active}
    tracker["last_timestamp"] = timestamp
    # Callers can annotate snapshots without mutating the next tracking update.
    return deepcopy(active)
