"""Progressive camera load & soak orchestrator: 4 -> 8 -> 16 -> 32 -> 48 -> 60+ cameras.

Executes bounded synthetic tiers using scripts/validate_streams.py while checking
configurable 75/80/85 resource policies between tiers. Intended for dedicated
high-performance staging/production servers, not low-headroom laptops.
"""

import argparse
import getpass
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.services.resource_guard import ResourceGuard

DEFAULT_TIERS = [4, 8, 16, 32, 48, 60]
SOAK_PROFILES = {
    "smoke": 1860,
    "integration": 7200,
    "operational": 28800,
    "day": 86400,
    "stability": 259200,
}


def find_latest_stream_report(directory, after_ts):
    candidates = sorted(directory.glob("streams-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        if path.stat().st_mtime >= after_ts - 2:
            return path
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tiers", default=",".join(map(str, DEFAULT_TIERS)),
                        help="Comma-separated camera tiers (default: 4,8,16,32,48,60)")
    parser.add_argument("--duration", type=int, default=120,
                        help="Seconds per tier (default: 120; ignored if --soak is used)")
    parser.add_argument("--soak", choices=sorted(SOAK_PROFILES), default="",
                        help="Run a single sustained soak profile (smoke=31m, integration=2h, operational=8h, day=24h, stability=72h)")
    parser.add_argument("--viewers", type=int, default=0, help="Concurrent playlist viewer pollers (0-4)")
    parser.add_argument("--warn", type=float, default=75)
    parser.add_argument("--reduce", type=float, default=80)
    parser.add_argument("--block", type=float, default=85)
    parser.add_argument("--max-p95-ms", type=float, default=500.0, help="Fail tier if API p95 latency exceeds ms")
    parser.add_argument("--network-interface", default="")
    parser.add_argument("--network-mbps", type=float, default=0)
    parser.add_argument("--dry-run", action="store_true", help="Inspect telemetry and print execution plan without starting cameras")
    parser.add_argument("--prompt-password", action="store_true", help="Prompt once for the current validation administrator password")
    args = parser.parse_args()

    tiers = [int(item.strip()) for item in args.tiers.split(",") if item.strip()]
    duration = SOAK_PROFILES[args.soak] if args.soak else args.duration
    if args.soak:
        tiers = [tiers[-1]]

    guard = ResourceGuard({
        "storage": ROOT,
        "resource_thresholds": (args.warn, args.reduce, args.block),
        "resource_network_interface": args.network_interface,
        "resource_network_mbps": args.network_mbps,
    })

    baseline = guard.snapshot()
    print(f"Baseline telemetry: level={baseline['level']} admit_new={baseline['admit_new']} metrics={baseline['metrics']}")
    if args.dry_run:
        print(json.dumps({
            "mode": "dry_run",
            "tiers": tiers,
            "duration_seconds": duration,
            "thresholds": [args.warn, args.reduce, args.block],
            "pass_criteria": {
                "all_streams_online_and_recording": True,
                "zero_harness_failures": True,
                "api_p95_ms_max": args.max_p95_ms,
                "max_resource_level": "reduce_before_block",
            },
            "baseline": baseline,
        }, indent=2))
        return

    out_dir = ROOT / "storage/deployment-validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    child_env = os.environ.copy()
    if args.prompt_password:
        child_env["VMS_VALIDATION_PASSWORD"] = getpass.getpass("Current administrator password: ")
    tier_results = []
    for tier in tiers:
        guard.last_sample = 0
        snap = guard.snapshot()
        if not snap["admit_new"]:
            print(f"Tier {tier} skipped safely: resource pressure level={snap['level']} metrics={snap['metrics']}")
            tier_results.append({"tier": tier, "status": "blocked_by_resource_guard", "telemetry": snap})
            break

        started = time.time()
        cmd = [
            sys.executable, str(ROOT / "scripts/validate_streams.py"),
            "--count", str(tier),
            "--duration", str(duration),
            "--viewers", str(args.viewers),
            "--warn", str(args.warn),
            "--reduce", str(args.reduce),
            "--block", str(args.block),
        ]
        if args.network_interface:
            cmd += ["--network-interface", args.network_interface, "--network-mbps", str(args.network_mbps)]
        print(f"\n=== Running Tier {tier} cameras ({duration}s) ===")
        proc = subprocess.run(cmd, cwd=str(ROOT), env=child_env, check=False)
        report_file = find_latest_stream_report(out_dir, started)
        report_data = json.loads(report_file.read_text()) if report_file else {}
        p95 = report_data.get("api_p95_ms")
        passed = proc.returncode == 0 and (p95 is None or p95 <= args.max_p95_ms) and not report_data.get("failures")
        tier_results.append({
            "tier": tier,
            "status": "passed" if passed else "failed",
            "returncode": proc.returncode,
            "api_p50_ms": report_data.get("api_p50_ms"),
            "api_p95_ms": p95,
            "failures": report_data.get("failures", []),
            "evidence_file": report_file.name if report_file else None,
        })
        if not passed:
            print(f"Stopping progression after tier {tier} did not pass.")
            break

    summary_path = out_dir / f"progressive-load-{int(time.time())}.json"
    summary = {
        "generated_at": time.time(),
        "requested_tiers": tiers,
        "duration_seconds": duration,
        "pass_criteria": {"max_api_p95_ms": args.max_p95_ms, "require_zero_failures": True},
        "results": tier_results,
    }
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\nSummary written: {summary_path}")
    if not tier_results or any(item["status"] != "passed" for item in tier_results):
        sys.exit(1)


if __name__ == "__main__":
    main()
