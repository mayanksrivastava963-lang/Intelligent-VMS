"""Bounded resource sampling and admission policy; never stops active recordings."""
import json
import logging
import math
from pathlib import Path
import subprocess
import time
from threading import Lock

import psutil

logger = logging.getLogger(__name__)


def pressure_level(metrics, thresholds=(75, 80, 85)):
    values = [value for value in metrics.values() if value is not None and math.isfinite(value)]
    peak = max(values, default=0)
    return ("block" if peak >= thresholds[2] else "reduce" if peak >= thresholds[1]
            else "warn" if peak >= thresholds[0] else "normal")


class ResourceGuard:
    def __init__(self, settings):
        self.settings = settings
        self.lock = Lock()
        self.cached = None
        self.previous_net = None
        self.previous_cpu = None
        self.last_sample = 0.0

    def snapshot(self):
        with self.lock:
            now = time.monotonic()
            if self.cached is not None and now - self.last_sample < 5:
                return self.cached
            metrics = dict.fromkeys(("cpu", "ram", "storage", "gpu", "vram", "network"))
            try:
                metrics.update(cpu=psutil.cpu_percent(interval=0.1), ram=psutil.virtual_memory().percent,
                               storage=psutil.disk_usage(str(self.settings["storage"])).percent)
            except (OSError, psutil.Error):
                pass  # Missing essential telemetry blocks allocation, not recording.
            # Docker's visible host RAM is not its memory allocation. Consider both.
            try:
                limit = int(Path("/sys/fs/cgroup/memory.max").read_text())
                used = int(Path("/sys/fs/cgroup/memory.current").read_text())
                metrics["ram"] = max(metrics["ram"] or 0, used * 100 / limit)
            except (OSError, ValueError, ZeroDivisionError):
                pass
            try:
                quota, period = map(int, Path("/sys/fs/cgroup/cpu.max").read_text().split())
                usage = int(dict(line.split() for line in Path("/sys/fs/cgroup/cpu.stat").read_text().splitlines())["usage_usec"])
                if self.previous_cpu:
                    elapsed, old_usage = self.previous_cpu
                    metrics["cpu"] = max(metrics["cpu"] or 0, (usage-old_usage) / ((now-elapsed)*1000000) * period/quota*100)
                self.previous_cpu = (now, usage)
            except (OSError, ValueError, KeyError, ZeroDivisionError):
                pass
            try:
                result = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                                         "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=1)
                rows = [list(map(float, line.split(","))) for line in result.stdout.splitlines() if line.strip()]
                if result.returncode == 0 and rows:
                    metrics["gpu"] = max(row[0] for row in rows)
                    metrics["vram"] = max(row[1] / row[2] * 100 for row in rows if row[2] > 0)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
            interface = self.settings.get("resource_network_interface", "")
            capacity = self.settings.get("resource_network_mbps", 0)
            try:
                counters = psutil.net_io_counters(pernic=True).get(interface) if interface else None
            except (OSError, psutil.Error):
                counters = None
            if counters is not None and capacity > 0:
                current = (counters.bytes_sent, counters.bytes_recv)
                if self.previous_net:
                    before, old = self.previous_net
                    metrics["network"] = max(0, *(a-b for a,b in zip(current, old))) * 8 / (now-before) / (capacity*1000000) * 100
                self.previous_net = (now, current)
            # Optional host-agent file compensates for Docker Desktop/VM visibility.
            # The file must be an administrator-owned, read-only mount in containers.
            telemetry = self.settings.get("resource_host_file")
            host_stale = False
            if telemetry:
                try:
                    path = Path(telemetry)
                    if path.stat().st_size > 16384:
                        raise ValueError("Oversized telemetry")
                    data = json.loads(path.read_text())
                    if not 0 <= time.time()-float(data["sampled_at"]) <= 15:
                        raise ValueError("Stale telemetry")
                    for key, value in data["metrics"].items():
                        if key in metrics and value is not None and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
                            metrics[key] = max(metrics[key] or 0, value)
                except (OSError, ValueError, KeyError, TypeError):
                    host_stale = True
            thresholds = self.settings.get("resource_thresholds", (75, 80, 85))
            level = pressure_level(metrics, thresholds)
            required = set(self.settings.get("resource_required_metrics", [])) | {"cpu", "ram", "storage"}
            missing = sorted(key for key in required if metrics.get(key) is None)
            if host_stale or missing:
                level = "block"
            previous = self.cached["level"] if self.cached else None
            levels = ["normal", "warn", "reduce", "block"]
            if previous in levels[1:] and levels.index(previous) > levels.index(level):
                release = thresholds[levels.index(previous)-1] - self.settings.get("resource_hysteresis", 3)
                if max((v for v in metrics.values() if v is not None), default=0) >= release:
                    level = previous
            result = {"sampled_at": time.time(), "metrics": metrics, "level": level,
                      "thresholds": list(thresholds), "unknown": [k for k,v in metrics.items() if v is None],
                      "host_telemetry_stale": host_stale, "missing_required": missing,
                      "admit_new": level != "block", "optional_processing": level not in {"reduce", "block"},
                      "scope": "process-visible host plus cgroup; external host telemetry only when configured"}
            if level != previous:
                log = logger.info if level == "normal" else logger.warning
                log("Resource policy state=%s; metrics=%s; missing=%s; host_stale=%s; existing recordings preserved",
                               level, metrics, missing, host_stale)
            self.cached, self.last_sample = result, now
            return result
