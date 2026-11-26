"""Publish synthetic RTSP feeds and measure the deployed VMS; never use company footage."""

import argparse
import json
import os
import shutil
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import imageio_ffmpeg
import psutil
from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[1]


def request(base, path, cookie="", method="GET", payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"X-VMS-Request": "1"}
    if cookie:
        headers["Cookie"] = cookie
    if body is not None:
        headers["Content-Type"] = "application/json"
    started = time.perf_counter()
    with urllib.request.urlopen(urllib.request.Request(
        base + path, data=body, headers=headers, method=method,
    ), timeout=20) as response:
        text = response.read().decode()
        return (json.loads(text) if text else None,
                (time.perf_counter() - started) * 1000, response.headers.get("Set-Cookie", ""))


def percentile(numbers, percent):
    values = sorted(numbers)
    return values[min(len(values) - 1, round((len(values) - 1) * percent))]


def gpu_usage():
    if not shutil.which("nvidia-smi"):
        return "unavailable"
    result = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
                             "--format=csv,noheader,nounits"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def container_usage():
    if not shutil.which("docker"):
        return None
    result = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}"],
                            capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        return None
    rows = []
    for line in result.stdout.splitlines():
        item = json.loads(line)
        if "intelligent-vms" in item.get("Name", ""):
            rows.append({key: item.get(key) for key in ("Name", "CPUPerc", "MemUsage", "NetIO", "BlockIO", "PIDs")})
    return rows


def database_connections():
    url = os.getenv("BENCHMARK_DATABASE_URL")
    if not url:
        return None
    engine = create_engine(url, pool_size=1, max_overflow=0)
    try:
        with engine.connect() as connection:
            return connection.execute(text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
            )).scalar_one()
    finally:
        engine.dispose()


def observed_fps(progress_files, elapsed):
    rates = []
    for progress in progress_files:
        progress.flush()
        lines = Path(progress.name).read_text(errors="ignore").splitlines()
        frames = [int(line.split("=", 1)[1]) for line in lines if line.startswith("frame=")]
        if frames:
            rates.append(round(frames[-1] / elapsed, 2))
    return rates


def main():
    parser = argparse.ArgumentParser(description="Synthetic RTSP load test on a high-resource server")
    parser.add_argument("--run", action="store_true", help="Required to launch the test")
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--api", default="https://127.0.0.1")
    parser.add_argument("--publish", default="rtsp://127.0.0.1:8554")
    args = parser.parse_args()
    if not args.run or not 1 <= args.count <= 60 or args.duration < 10:
        parser.error("Use --run with --count 1..60 and --duration at least 10 seconds")
    password = os.getenv("VMS_BENCHMARK_PASSWORD")
    if not password:
        parser.error("Set VMS_BENCHMARK_PASSWORD in the process environment")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        parser.error("Node/npm is required to verify the frontend build")
    build = subprocess.run([npm, "--prefix", "frontend", "run", "build"],
                           cwd=ROOT, capture_output=True, text=True)
    if build.returncode != 0:
        raise RuntimeError("Frontend build failed; see npm output locally")
    ffmpeg = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
    output = ROOT / "storage" / "test-runs" / ("benchmark-" + uuid4().hex)
    output.mkdir(parents=True)
    cameras = []
    publishers = []
    progress_files = []
    login, _latency, set_cookie = request(args.api, "/api/auth/login", method="POST", payload={
        "username": os.getenv("VMS_BENCHMARK_USERNAME", "admin"), "password": password,
    })
    if not login["authenticated"]:
        raise RuntimeError("Benchmark sign-in failed")
    cookie = set_cookie.split(";", 1)[0]
    latencies = []
    started = time.time()
    try:
        for number in range(args.count):
            progress = (output / f"progress-{number}.txt").open("wb")
            progress_files.append(progress)
            command = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi",
                "-i", "testsrc2=size=160x90:rate=5", "-c:v", "libx264",
                "-preset", "ultrafast", "-tune", "zerolatency",
                "-progress", "pipe:1", "-stats_period", "5", "-f", "rtsp",
                f"{args.publish.rstrip('/')}/benchmark-{number}",
            ]
            publishers.append(subprocess.Popen(command, stdout=progress, stderr=subprocess.DEVNULL))
            camera, latency, _ = request(args.api, "/api/cameras/rtsp", cookie, "POST", {
                "name": f"Synthetic {number + 1:02d}", "location": "benchmark",
                "url": f"rtsp://mediamtx:8554/benchmark-{number}",
            })
            if "rtsp://" in json.dumps(camera):
                raise RuntimeError("Credential/source URL leaked in camera response")
            cameras.append(camera["id"])
            _result, latency_start, _ = request(args.api, f"/api/cameras/{camera['id']}/start", cookie, "POST")
            latencies.extend([latency, latency_start])
        time.sleep(min(10, args.duration))
        remaining = max(0, args.duration - 10)
        time.sleep(remaining)

        def poll(_number):
            result, elapsed, _ = request(args.api, "/api/cameras?limit=100", cookie)
            if "rtsp://" in json.dumps(result):
                raise RuntimeError("Credential/source URL leaked in camera list")
            return result, elapsed

        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(poll, range(max(16, remaining))))
        latencies.extend([elapsed for _result, elapsed in results])
        fps = observed_fps(progress_files, time.time() - started)
        online = sum(item["connection_status"] == "online" for item in results[-1][0]
                     if item["id"] in cameras)
        print(json.dumps({
            "requested_cameras": args.count, "online_cameras": online,
            "api_latency_ms_p50": round(statistics.median(latencies), 1),
            "api_latency_ms_p95": round(percentile(latencies, 0.95), 1),
            "api_latency_ms_max": round(max(latencies), 1),
            "host_cpu_percent": psutil.cpu_percent(interval=1),
            "host_ram_used_bytes": psutil.virtual_memory().used,
            "gpu_memory_mib_and_utilization_percent": gpu_usage(),
            "publisher_processes_alive": sum(process.poll() is None for process in publishers),
            "publisher_fps_p50": round(statistics.median(fps), 2) if fps else None,
            "publisher_fps_min": min(fps) if fps else None,
            "postgres_connections": database_connections(),
            "container_resources": container_usage(),
            "frontend_build": "passed",
            "elapsed_seconds": round(time.time() - started, 1),
            "progress_directory": str(output),
        }, indent=2))
    finally:
        for camera_id in cameras:
            try:
                request(args.api, f"/api/cameras/{camera_id}", cookie, "DELETE")
            except (urllib.error.URLError, TimeoutError):
                pass
        for process in publishers:
            if process.poll() is None:
                process.terminate()
        for process in publishers:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for progress in progress_files:
            progress.close()


if __name__ == "__main__":
    main()
