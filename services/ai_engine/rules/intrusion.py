"""Alert once when a confirmed person enters a configured polygon."""


def inside(point, polygon):
    x, y = point
    crossing = False
    for index, first in enumerate(polygon):
        second = polygon[(index + 1) % len(polygon)]
        if (first[1] > y) != (second[1] > y):
            edge_x = first[0] + (y - first[1]) * (second[0] - first[0]) / (second[1] - first[1])
            if x < edge_x:
                crossing = not crossing
    return crossing


def evaluate(tracks, polygon, seen):
    if len(polygon) < 3:
        return []
    events = []
    active = set()
    for track in tracks:
        if track["class_name"] != "person" or not track["confirmed"] or not track["observed"]:
            continue
        box = track["bbox"]
        point = ((box[0] + box[2]) / 2, box[3])
        if inside(point, polygon):
            active.add(track["track_id"])
            if track["track_id"] not in seen:
                events.append({"rule": "intrusion", "track_id": track["track_id"],
                               "message": "Person entered a restricted zone; review footage"})
    seen.intersection_update(active)
    seen.update(active)
    return events
