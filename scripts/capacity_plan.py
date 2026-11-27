"""Offline engineering estimates, not measured camera capacity."""

import argparse
import json
import math


def estimate(cameras, main_mbps, sub_mbps, days, viewers, tiles, duty=1.0, headroom=0.3):
    values = (cameras, main_mbps, sub_mbps, days, viewers, tiles, duty, headroom)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("All inputs must be finite")
    if min(cameras, main_mbps, days, tiles) <= 0 or min(sub_mbps, viewers, headroom) < 0 or not 0 < duty <= 1:
        raise ValueError("Invalid workload inputs")
    recording_mbps = cameras * main_mbps * duty
    daily_bytes = recording_mbps * 1_000_000 / 8 * 86400
    return {
        "kind": "theoretical_estimate_not_benchmark",
        "incoming_mbps": cameras * (main_mbps + sub_mbps),
        "outgoing_grid_mbps": viewers * min(tiles, cameras) * (sub_mbps or main_mbps),
        "average_recording_MB_per_second": recording_mbps / 8,
        "daily_storage_decimal_TB": daily_bytes / 1e12,
        "retention_storage_decimal_TB_with_headroom": daily_bytes * days * (1 + headroom) / 1e12,
        "headroom_fraction": headroom,
        "limitations": "Include audio in main bitrate; VBR peaks, RAID, playback/export and AI need separate measurement. CPU/GPU capacity is not inferred.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cameras", type=int, required=True)
    parser.add_argument("--main-mbps", type=float, required=True)
    parser.add_argument("--sub-mbps", type=float, default=0.5)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--viewers", type=int, default=1)
    parser.add_argument("--tiles", type=int, default=9)
    parser.add_argument("--duty", type=float, default=1)
    parser.add_argument("--headroom", type=float, default=0.3)
    args = parser.parse_args()
    try:
        print(json.dumps(estimate(args.cameras, args.main_mbps, args.sub_mbps, args.days,
                                  args.viewers, args.tiles, args.duty, args.headroom), indent=2))
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
