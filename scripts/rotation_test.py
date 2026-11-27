"""Repeatable recording segment rotation validator (default 1800s production boundary).

Requires an authenticated operator account from --env-file or --username/--password.
Never mark 30-minute rotation as validated unless executed with --segment-seconds 1800
across at least two completed segments on the target server.
"""

import argparse
import getpass
import http.cookiejar
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import dotenv_values


class ApiClient:
    def __init__(self, base_url, context):
        self.base_url = base_url.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context),
            urllib.request.HTTPCookieProcessor(self.jar),
        )

    def request(self, path, payload=None, method=None, headers=None, expect_json=True):
        body = None if payload is None else json.dumps(payload).encode()
        req_headers = {"X-VMS-Request": "1"}
        if payload is not None:
            req_headers["Content-Type"] = "application/json"
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(self.base_url + path, data=body, method=method, headers=req_headers)
        with self.opener.open(req, timeout=15) as resp:
            raw = resp.read()
            if expect_json:
                return resp.status, json.loads(raw)
            return resp.status, raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--segment-seconds", type=int, default=1800,
                        help="Configured RECORDING_SEGMENT_SECONDS (default: 1800)")
    parser.add_argument("--quick", action="store_true",
                        help="Developer quick check override (60s segments; does NOT certify 30-min rotation)")
    parser.add_argument("--api-url", default="", help="Override API base URL (default from env or https://localhost:8443)")
    parser.add_argument("--env-file", type=Path, default=None,
                        help="Path to validation.env or .env.production")
    parser.add_argument("--username", default="", help="Operator username if not using --env-file")
    parser.add_argument("--password", default="", help="Operator password if not using --env-file")
    parser.add_argument("--prompt-password", action="store_true",
                        help="Prompt privately for the current operator password")
    parser.add_argument("--ca-file", type=Path, default=None, help="TLS CA/fullchain certificate path")
    parser.add_argument("--insecure", action="store_true", help="Skip TLS verification (dev self-signed only)")
    parser.add_argument("--camera-id", default="", help="Camera UUID to monitor (auto-selects first running camera if omitted)")
    parser.add_argument("--timeout-factor", type=float, default=1.25,
                        help="Timeout multiplier over 2 segment cycles (default: 1.25)")
    parser.add_argument("--max-gap-seconds", type=float, default=15.0,
                        help="Maximum allowed gap between consecutive segment intervals (default: 15s)")
    parser.add_argument("--report", type=Path, default=None, help="Optional JSON output report path")
    args = parser.parse_args()

    if args.quick:
        args.segment_seconds = 60

    cfg = dotenv_values(args.env_file) if args.env_file and args.env_file.exists() else {}
    api_url = args.api_url or (f"https://localhost:{cfg['VMS_HTTPS_PORT']}" if cfg.get("VMS_HTTPS_PORT") else "https://localhost:8443")
    username = args.username or cfg.get("VMS_OPERATOR_USERNAME", "")
    password = (getpass.getpass("Current operator password: ") if args.prompt_password
                else args.password or cfg.get("VMS_OPERATOR_PASSWORD", ""))
    if not username or not password:
        raise SystemExit("Supply --env-file or both --username and --password")

    if args.insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    elif args.ca_file and args.ca_file.exists():
        ctx = ssl.create_default_context(cafile=str(args.ca_file))
    elif args.env_file and (args.env_file.parent / "tls/fullchain.pem").exists():
        ctx = ssl.create_default_context(cafile=str(args.env_file.parent / "tls/fullchain.pem"))
    else:
        ctx = ssl.create_default_context()

    client = ApiClient(api_url, ctx)
    client.request("/api/auth/login", {"username": username, "password": password})

    camera_id = args.camera_id
    if not camera_id:
        _, cameras = client.request("/api/cameras?limit=500")
        running = [c for c in cameras if c.get("status") == "running" and c.get("source_type") == "rtsp"]
        if not running:
            raise SystemExit("No running RTSP cameras found; start at least one camera before rotation testing")
        camera_id = running[0]["id"]
        print(f"Monitoring camera: {running[0].get('name')} ({camera_id})")

    started_at = time.time()
    wait_seconds = int(args.segment_seconds * 2 * args.timeout_factor + 120)
    print(f"Target segment_seconds={args.segment_seconds} ({'quick dev override' if args.segment_seconds < 1800 else 'production 30-minute boundary'})")
    print(f"Waiting up to {wait_seconds}s for at least 2 newly completed segments...")

    seen = set()
    completed = []
    live_checks = []
    while time.time() - started_at < wait_seconds:
        _, items = client.request(f"/api/videos?limit=25&camera_id={camera_id}")
        for item in items:
            if item["id"] not in seen and item.get("status") == "ready" and item.get("created_at", 0) >= started_at - 5:
                seen.add(item["id"])
                completed.append(item)
                print(f"  Completed segment #{len(completed)}: {item['filename']} duration={item.get('duration_seconds')}s bytes={item.get('bytes')}")
        try:
            _, playlist = client.request(f"/live/{camera_id}/index.m3u8", expect_json=False)
            live_checks.append(b"#EXTM3U" in playlist)
        except Exception:
            live_checks.append(False)
        if len(completed) >= 2:
            break
        time.sleep(15)

    failures = []
    completed.sort(key=lambda item: item["created_at"])
    if len(completed) < 2:
        failures.append(f"Expected >= 2 completed segments, observed {len(completed)}")

    playback_checks = []
    for item in completed:
        if (item.get("duration_seconds") or 0) <= 0 or item.get("bytes", 0) < 1024:
            failures.append(f"Invalid segment metadata for {item['id']}")
        _, detail = client.request(f"/api/videos/{item['id']}")
        segs = detail.get("segments", [])
        if not segs:
            failures.append(f"Recording {item['id']} has no playable segments")
            continue
        seg_url = segs[0]["playback_url"]
        status_code, sample = client.request(seg_url, headers={"Range": "bytes=0-1023"}, expect_json=False)
        ok = status_code == 206 and len(sample) > 0
        playback_checks.append({"video_id": item["id"], "status": status_code, "bytes": len(sample), "ok": ok})
        if not ok:
            failures.append(f"Playback range check failed for {seg_url} (status={status_code})")

    gaps = []
    for prev, nxt in zip(completed, completed[1:]):
        prev_end = prev["created_at"]
        nxt_start_est = nxt["created_at"] - (nxt.get("duration_seconds") or 0)
        gap = nxt_start_est - prev_end
        gaps.append(round(gap, 2))
        if abs(gap) > args.max_gap_seconds:
            failures.append(f"Timeline gap/skew {gap:.2f}s exceeded {args.max_gap_seconds}s")

    result = {
        "mode": "production_1800s_rotation" if args.segment_seconds >= 1800 else "quick_non_production_override",
        "segment_seconds": args.segment_seconds,
        "camera_id": camera_id,
        "segments_verified": len(completed),
        "playback_checks": playback_checks,
        "estimated_gaps_seconds": gaps,
        "live_hls_independent": any(live_checks),
        "failures": failures,
        "passed": len(failures) == 0 and args.segment_seconds >= 1800,
    }
    if args.report:
        args.report.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
