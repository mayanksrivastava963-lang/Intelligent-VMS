import json
import math
import sys

import av


def inspect_video(path):
    with av.open(path, options={"protocol_whitelist": "file,pipe"}) as container:
        if not container.streams.video:
            raise ValueError("No video stream")
        video = container.streams.video[0]
        duration = float(container.duration / av.time_base) if container.duration else 0
        if not duration and video.duration is not None:
            duration = float(video.duration * video.time_base)
        if not duration:
            duration = find_duration_from_packets(container, video)
        if not math.isfinite(duration) or not 0 < duration <= 48 * 3600:
            raise ValueError("Video must have a known duration of at most 48 hours")
        if not 0 < video.width <= 8192 or not 0 < video.height <= 8192 or video.width * video.height > 34_000_000:
            raise ValueError("Unsupported video resolution")
        return {"duration_seconds": duration, "width": video.width, "height": video.height,
                "has_audio": bool(container.streams.audio)}


def find_duration_from_packets(container, video):
    latest_end = 0.0
    average_rate = float(video.average_rate) if video.average_rate else 0
    for packet in container.demux(video):
        if packet.pts is None:
            continue
        packet_time_base = float(packet.time_base or video.time_base)
        packet_duration = packet.duration * packet_time_base if packet.duration else 0
        packet_end = packet.pts * packet_time_base + packet_duration
        latest_end = max(latest_end, packet_end)
        if latest_end > 48 * 3600:
            raise ValueError("Video duration exceeds 48 hours")
    if latest_end and average_rate:
        latest_end += 1 / average_rate
    return latest_end


if __name__ == "__main__":
    try:
        print(json.dumps(inspect_video(sys.argv[1])))
    except Exception:
        print("Invalid or unsupported video", file=sys.stderr)
        raise SystemExit(1)
