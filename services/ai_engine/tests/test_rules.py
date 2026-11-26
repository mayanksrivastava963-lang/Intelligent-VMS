from services.ai_engine.rules import intrusion, loitering, unattended_object


def track(track_id, name, box):
    return {"track_id": track_id, "class_name": name, "bbox": box,
            "confirmed": True, "observed": True}


def test_intrusion_alerts_once_per_entry():
    zone = [[0, 0], [100, 0], [100, 100], [0, 100]]
    person = track(1, "person", [30, 20, 50, 60])
    seen = set()
    assert len(intrusion.evaluate([person], zone, seen)) == 1
    assert intrusion.evaluate([person], zone, seen) == []
    assert intrusion.evaluate([], zone, seen) == []
    assert len(intrusion.evaluate([person], zone, seen)) == 1


def test_loitering_uses_elapsed_time():
    person = track(1, "person", [30, 20, 50, 60])
    entered = {}
    alerted = set()
    assert loitering.evaluate([person], 10, 30, entered, alerted) == []
    assert loitering.evaluate([person], 39, 30, entered, alerted) == []
    assert len(loitering.evaluate([person], 40, 30, entered, alerted)) == 1
    assert loitering.evaluate([person], 50, 30, entered, alerted) == []


def test_unattended_object_requires_stationary_bag_without_person():
    bag = track(2, "backpack", [30, 20, 50, 60])
    person = track(1, "person", [40, 10, 60, 80])
    waiting = {}
    alerted = set()
    assert unattended_object.evaluate([bag, person], 0, 10, 80, waiting, alerted) == []
    assert unattended_object.evaluate([bag], 1, 10, 80, waiting, alerted) == []
    assert unattended_object.evaluate([bag], 10, 10, 80, waiting, alerted) == []
    assert len(unattended_object.evaluate([bag], 11, 10, 80, waiting, alerted)) == 1
    assert unattended_object.evaluate([bag], 20, 10, 80, waiting, alerted) == []
