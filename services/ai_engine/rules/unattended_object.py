"""Review stationary bags after no tracked person remains nearby."""

import math


BAG_CLASSES = {"backpack", "handbag", "suitcase"}


def evaluate(tracks, now, threshold, distance, waiting, alerted):
    people = [track for track in tracks if track["class_name"] == "person" and track["observed"]]
    active = set()
    events = []
    for track in tracks:
        if track["class_name"] not in BAG_CLASSES or not track["confirmed"] or not track["observed"]:
            continue
        box = track["bbox"]
        center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        nearby = False
        for person in people:
            person_box = person["bbox"]
            person_center = ((person_box[0] + person_box[2]) / 2,
                             (person_box[1] + person_box[3]) / 2)
            if math.dist(center, person_center) <= distance:
                nearby = True
                break
        track_id = track["track_id"]
        active.add(track_id)
        if nearby:
            waiting.pop(track_id, None)
            alerted.discard(track_id)
            continue
        previous = waiting.get(track_id)
        if previous is None or math.dist(previous[1], center) > distance / 4:
            waiting[track_id] = (now, center)
            alerted.discard(track_id)
        elif now - previous[0] >= threshold and track_id not in alerted:
            alerted.add(track_id)
            events.append({"rule": "unattended_object", "track_id": track_id,
                           "message": "Stationary bag without a nearby person; review footage"})
    for track_id in list(waiting):
        if track_id not in active:
            del waiting[track_id]
            alerted.discard(track_id)
    return events
