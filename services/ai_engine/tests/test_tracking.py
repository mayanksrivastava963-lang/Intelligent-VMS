from copy import deepcopy

import pytest

from services.ai_engine.tracking.tracker import create_tracker, reset_tracker, update_tracker


def detection(x=0, label=1, name="person"):
    return {"class_id": label, "class_name": name, "confidence": 0.9,
            "bbox": [x, 0, x + 20, 40]}


def test_motion_and_confirmation():
    tracker = create_tracker("entrance", history_size=2)
    first = update_tracker(tracker, [detection()], 0)[0]
    assert first["status"] == "tentative"
    update_tracker(tracker, [detection(5)], 1)
    third = update_tracker(tracker, [detection(10)], 2)[0]
    assert third["track_id"] == first["track_id"]
    assert third["status"] == "confirmed"
    assert third["velocity"] == [5, 0]
    assert third["first_seen"] == 0
    assert third["last_seen"] == 2
    assert len(third["history"]) == 2


def test_missed_detection_recovery_and_expiration():
    tracker = create_tracker("entrance", max_missing_seconds=2, min_hits=1)
    update_tracker(tracker, [detection()], 0)
    update_tracker(tracker, [detection(5)], 1)
    lost = update_tracker(tracker, [], 2)[0]
    assert lost["status"] == "lost"
    assert not lost["observed"]
    assert lost["last_seen"] == 1
    assert len(lost["history"]) == 2
    recovered = update_tracker(tracker, [detection(15)], 3)[0]
    assert recovered["track_id"] == 1
    assert recovered["observed"]
    assert update_tracker(tracker, [], 5.01) == []
    assert update_tracker(tracker, [detection(15)], 6)[0]["track_id"] == 2


def test_reordered_objects_keep_ids():
    tracker = create_tracker("entrance")
    update_tracker(tracker, [detection(0), detection(100)], 0)
    tracks = update_tracker(tracker, [detection(95), detection(5)], 1)
    assert [(track["track_id"], track["bbox"][0]) for track in tracks] == [(1, 5), (2, 95)]


def test_global_matching_avoids_greedy_identity_loss():
    tracker = create_tracker("entrance")
    update_tracker(tracker, [detection(0), detection(12)], 0)
    tracks = update_tracker(tracker, [detection(6), detection(-8)], 1)
    assert len(tracks) == 2
    assert tracks[0]["bbox"][0] == -8
    assert tracks[1]["bbox"][0] == 6


def test_class_changes_do_not_reuse_identity():
    tracker = create_tracker("entrance")
    update_tracker(tracker, [detection()], 0)
    tracks = update_tracker(tracker, [detection(label=3, name="car")], 1)
    assert tracks[0]["status"] == "lost"
    assert tracks[1]["track_id"] == 2


def test_cameras_and_sessions_are_isolated():
    first = create_tracker("one")
    second = create_tracker("two")
    a = update_tracker(first, [detection()], 0)[0]
    b = update_tracker(second, [detection()], 0)[0]
    assert (a["camera_id"], a["session_id"], a["track_id"]) != (b["camera_id"], b["session_id"], b["track_id"])
    reset_tracker(first)
    assert len(second["tracks"]) == 1
    assert update_tracker(first, [detection()], 0)[0]["track_id"] == 2


@pytest.mark.parametrize("timestamp", [-1, float("nan"), float("inf"), 1, 0.5, None])
def test_invalid_timestamp_is_atomic(timestamp):
    tracker = create_tracker("entrance")
    update_tracker(tracker, [detection()], 1)
    previous = deepcopy(tracker)
    with pytest.raises(ValueError):
        update_tracker(tracker, [detection(5)], timestamp)
    assert tracker == previous


@pytest.mark.parametrize("bad", [{}, {"bbox": [0, 0, 0, 10]}, {"confidence": float("nan")},
                                 {"class_id": "1"}, {"bbox": [0, 0, float("inf"), 20]}])
def test_invalid_detection_is_atomic(bad):
    tracker = create_tracker("entrance")
    update_tracker(tracker, [detection()], 0)
    previous = deepcopy(tracker)
    value = detection()
    if bad:
        value.update(bad)
    else:
        value = {}
    with pytest.raises(ValueError):
        update_tracker(tracker, [value], 1)
    assert tracker == previous


def test_capacity_is_bounded_without_partial_updates():
    tracker = create_tracker("entrance", max_tracks=1)
    update_tracker(tracker, [detection()], 0)
    previous = deepcopy(tracker)
    with pytest.raises(ValueError, match="capacity"):
        update_tracker(tracker, [detection(100)], 1)
    assert tracker == previous


def test_returned_snapshot_cannot_mutate_state():
    tracker = create_tracker("entrance")
    tracks = update_tracker(tracker, [detection()], 0)
    tracks[0]["bbox"][0] = 999
    tracks[0]["history"].clear()
    assert tracker["tracks"][1]["bbox"][0] == 0
    assert len(tracker["tracks"][1]["history"]) == 1


def test_confirmation_requires_consecutive_observations():
    tracker = create_tracker("entrance", min_hits=2)
    update_tracker(tracker, [detection()], 0)
    update_tracker(tracker, [], 0.5)
    assert not update_tracker(tracker, [detection()], 1)[0]["confirmed"]
    assert update_tracker(tracker, [detection()], 1.5)[0]["confirmed"]
