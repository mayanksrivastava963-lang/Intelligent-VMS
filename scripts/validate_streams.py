"""Isolated synthetic RTSP validation with bounded load and no footage deletion."""
import argparse
import getpass
import http.cookiejar
import json
import os
import shutil
import ssl
import statistics
import subprocess
import time
import sys
import urllib.error
import urllib.request
from pathlib import Path
import psutil
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.services.resource_guard import ResourceGuard


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--warn", type=float, default=75)
    parser.add_argument("--reduce", type=float, default=80)
    parser.add_argument("--block", type=float, default=85)
    parser.add_argument("--network-interface", default="")
    parser.add_argument("--network-mbps", type=float, default=0)
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--viewers", type=int, default=0)
    parser.add_argument("--keep", action="store_true", help="Keep this run's streams running after measurement")
    parser.add_argument("--prompt-password", action="store_true", help="Prompt privately for the current administrator password")
    args = parser.parse_args()
    if args.count < 1 or not 0 < args.warn < args.reduce < args.block <= 100:
        parser.error("Positive camera count and 0 < warning < reduction < block <= 100 required")
    guard = ResourceGuard(dict(storage=ROOT, resource_thresholds=(args.warn, args.reduce, args.block),
                               resource_network_interface=args.network_interface, resource_network_mbps=args.network_mbps))
    if args.duration < 30 or args.duration > 259200 or not 0 <= args.viewers <= 4:
        parser.error("Use 30..259200 seconds and 0..4 viewers")
    if not guard.snapshot()["admit_new"]:
        raise SystemExit("Resource admission blocked before testing; free resources or use a suitably sized server")
    config = dotenv_values(ROOT / "storage/deployment-validation/validation.env")
    docker = shutil.which("docker") or str(Path(os.getenv("LOCALAPPDATA", "")) / "Programs/DockerDesktop/resources/bin/docker.exe")
    if not Path(docker).is_file():
        raise SystemExit("Docker CLI not found")
    assert config["COMPOSE_PROJECT_NAME"] == "intelligent-vms-validation"
    base = "https://localhost:" + config["VMS_HTTPS_PORT"]
    context = ssl.create_default_context(cafile=str(ROOT / "storage/deployment-validation/tls/fullchain.pem"))
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), urllib.request.HTTPCookieProcessor(jar))
    def request(path, payload=None, method=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(base + path, data=data, method=method,
            headers={"X-VMS-Request": "1", "Content-Type": "application/json"})
        with opener.open(req, timeout=10) as response:
            body = response.read()
            return json.loads(body) if response.headers.get_content_type() == "application/json" else body
    password = (os.getenv("VMS_VALIDATION_PASSWORD") or
                (getpass.getpass("Current administrator password: ") if args.prompt_password
                 else config["VMS_OPERATOR_PASSWORD"]))
    request("/api/auth/login", {"username": config["VMS_OPERATOR_USERNAME"], "password": password})
    existing = request("/api/cameras?limit=500")
    if any(c["status"] == "running" for c in existing):
        raise RuntimeError("Stop previous validation streams before a new isolated run")
    run = str(int(time.time()))
    report_path = ROOT / "storage/deployment-validation" / ("streams-" + run + ".json")
    cameras, containers, samples, latencies, failures = [], [], [], [], []
    expected_denials = {}
    for path in ("/api/cameras", "/live/00000000-0000-0000-0000-000000000000/index.m3u8"):
        try:
            urllib.request.urlopen(base + path, context=context, timeout=5)
            expected_denials[path] = "UNEXPECTED_SUCCESS"
        except urllib.error.HTTPError as error:
            expected_denials[path] = error.code
    started = time.monotonic()
    try:
        for number in range(args.count):
            guard.last_sample = 0  # Fresh check before every additional publisher.
            if not guard.snapshot()["admit_new"]:
                failures.append("Resource admission blocked during escalation")
                break
            name = f"vms-validation-publisher-{run}-{number}"
            result = subprocess.run([docker, "run", "-d", "--name", name,
                "--network", "intelligent-vms-validation_synthetic", "--memory", "128m", "--cpus", "0.5",
                "--pids-limit", "32", "--log-driver", "local", "--log-opt", "max-size=1m",
                "intelligent-vms-api:0.1.0", "ffmpeg", "-hide_banner", "-loglevel", "error", "-re",
                "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=5", "-threads", "1",
                "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-g", "10",
                "-pix_fmt", "yuv420p", "-b:v", "256k", "-f", "rtsp", "-rtsp_transport", "tcp",
                f"rtsp://172.30.86.10:8554/synthetic-{run}-{number}"], capture_output=True, text=True, check=True)
            containers.append(name)
            camera = request("/api/cameras/rtsp", {"name": f"Synthetic {run}-{number}", "location": "ISOLATED VALIDATION",
                "url": f"rtsp://172.30.86.10:8554/synthetic-{run}-{number}"})
            cameras.append(camera["id"])
            request(f"/api/cameras/{camera['id']}/start", {}, "POST")
        started = time.monotonic()
        while not failures and time.monotonic() - started < args.duration:
            before = time.perf_counter()
            try:
                rows = [c for c in request("/api/cameras?limit=500") if c["id"] in cameras]
                latencies.append((time.perf_counter() - before) * 1000)
                online = sum(c["connection_status"] == "online" for c in rows)
                recording = sum(c.get("recording_status") == "online" for c in rows)
                pressure = guard.snapshot()
                if args.viewers and pressure["optional_processing"]:
                    for _ in range(args.viewers):
                        for camera in cameras:
                            playlist = request(f"/live/{camera}/index.m3u8")
                            assert b"#EXTM3U" in playlist
                resources = subprocess.run([docker, "stats", "--no-stream", "--format", "{{json .}}"],
                    capture_output=True, text=True, timeout=20)
                stats = [json.loads(line) for line in resources.stdout.splitlines() if line]
                stats = [s for s in stats if "vms" in s.get("Name", "")]
                sample = dict(elapsed_seconds=round(time.monotonic()-started, 1), online=online, recording=recording,
                    resource_policy=pressure,
                    host_cpu=psutil.cpu_percent(interval=0.2), host_ram_percent=psutil.virtual_memory().percent,
                    containers=stats)
                samples.append(sample)
                if not pressure["admit_new"]:
                    failures.append("Safety stop: configured resource admission threshold reached")
                    break
                print(json.dumps({k:v for k,v in sample.items() if k != "containers"}), flush=True)
            except Exception as error:
                failures.append(type(error).__name__)
                print("Validation sample failed:", type(error).__name__, flush=True)
                if len(failures) >= 3:
                    break
            time.sleep(10)
    finally:
        if not args.keep or failures:
            for camera in cameras:
                try:
                    request(f"/api/cameras/{camera}/stop", {}, "POST")
                except Exception:
                    failures.append("Camera stop request failed")
            for name in containers:
                subprocess.run([docker, "stop", "-t", "5", name], capture_output=True, timeout=15)
        # Keep test recordings, metadata and stopped containers for evidence.
        report = dict(camera_ids=cameras, publishers=containers, count=args.count, requested_duration=args.duration,
            elapsed_seconds=round(time.monotonic()-started, 1), codec="H.264", resolution="320x180", fps=5,
            target_bitrate_kbps=256, gop_frames=10, ai_enabled=False, playlist_pollers=args.viewers,
            viewer_limit="Playlist polling is not browser decoding or end-to-end viewer latency",
            expected_denials=expected_denials, failures=failures, samples=samples,
            api_p50_ms=statistics.median(latencies) if latencies else None,
            api_p95_ms=sorted(latencies)[int((len(latencies)-1)*0.95)] if latencies else None)
        report_path.write_text(json.dumps(report, indent=2))
        print("Evidence:", report_path)
    if not samples or not any(s["online"] == args.count and s["recording"] == args.count for s in samples):
        failures.append("Not all streams reached online recording state")
        report["failures"] = failures
        report_path.write_text(json.dumps(report, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
