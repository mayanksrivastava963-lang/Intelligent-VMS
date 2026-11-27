"""Optional host telemetry publisher. Mount output directory read-only into containers."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.services.resource_guard import ResourceGuard


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--storage", type=Path, default=ROOT)
    parser.add_argument("--network-interface", default="")
    parser.add_argument("--network-mbps", type=float, default=0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    guard = ResourceGuard(dict(storage=args.storage, resource_network_interface=args.network_interface,
                               resource_network_mbps=args.network_mbps))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        while True:
            snapshot = guard.snapshot()
            temporary = args.output.with_suffix(".tmp")
            temporary.write_text(json.dumps(snapshot))
            temporary.replace(args.output)
            if args.once:
                break
            time.sleep(5)
    except KeyboardInterrupt:
        pass  # Telemetry expires; consumers refuse new work rather than assume safety.


if __name__ == "__main__":
    main()
