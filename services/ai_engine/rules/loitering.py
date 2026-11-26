"""Timed person dwell alerts based on monotonic live-stream time."""

from services.ai_engine.rules.intrusion import inside


def evaluate(tracks, now, threshold, entered, alerted, polygon=None):
    active = set()
    events = []
    for track in tracks:
        if track["class_name"] != "person" or not track["confirmed"] or not track["observed"]:
            continue
        box = track["bbox"]
        point = ((box[0] + box[2]) / 2, box[3])
        if polygon and not inside(point, polygon):
            continue
        track_id = track["track_id"]
        active.add(track_id)
        entered.setdefault(track_id, now)
        if now - entered[track_id] >= threshold and track_id not in alerted:
            alerted.add(track_id)
            events.append({"rule": "loitering", "track_id": track_id,
                           "message": "Person remained in a monitored area; review footage"})
    for track_id in list(entered):
        if track_id not in active:
            del entered[track_id]
            alerted.discard(track_id)
    return events
