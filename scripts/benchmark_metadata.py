"""Bounded isolated camera metadata benchmark. Opens no streams or company DB."""

import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psutil
from backend.app.database.session import create_database
from backend.app.services.rtsp import create_rtsp_camera, list_rtsp_cameras


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix="vms-metadata-") as temp:
        engine = create_database("sqlite:///" + (Path(temp) / "isolated.db").as_posix())
        try:
            count = 0
            for target in (4, 16, 32, 64, 128, 256):
                while count < target:
                    create_rtsp_camera(engine, "synthetic-only-key-" * 3, f"Metadata {count}", "isolated",
                                       "rtsp://192.0.2.1/never-connected")
                    count += 1
                samples = []
                for _ in range(25):
                    start = time.perf_counter()
                    assert len(list_rtsp_cameras(engine, limit=500)) == target
                    samples.append((time.perf_counter() - start) * 1000)
                results.append(dict(registered_rows=target, active_streams=0, iterations=25,
                                    median_ms=round(statistics.median(samples), 3),
                                    p95_ms=round(sorted(samples)[23], 3)))
        finally:
            engine.dispose()
    print(json.dumps(dict(kind="isolated_metadata_only_not_stream_capacity", os=platform.system(),
                          python=platform.python_version(), logical_cpus=psutil.cpu_count(),
                          ram_bytes=psutil.virtual_memory().total, results=results), indent=2))


if __name__ == "__main__":
    main()
