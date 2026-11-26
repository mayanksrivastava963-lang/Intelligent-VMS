"""Read host resource usage without exposing paths or process details."""

import time

import psutil


def read_system_metrics(storage):
    cpu_percent = psutil.cpu_percent(interval=0.15)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(storage))
    process = psutil.Process()
    now = time.time()
    return {
        "sampled_at": now,
        "cpu": {
            "percent": cpu_percent,
            "logical_cores": psutil.cpu_count(),
            "physical_cores": psutil.cpu_count(logical=False),
        },
        "memory": {
            "percent": memory.percent,
            "used_bytes": memory.total - memory.available,
            "available_bytes": memory.available,
            "total_bytes": memory.total,
        },
        "disk": {
            "percent": disk.percent,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "total_bytes": disk.total,
        },
        "host_uptime_seconds": max(0, now - psutil.boot_time()),
        "api_memory_bytes": process.memory_info().rss,
        "api_uptime_seconds": max(0, now - process.create_time()),
    }
