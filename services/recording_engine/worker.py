import argparse
import csv
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from threading import Event
from uuid import uuid4

import imageio_ffmpeg

from backend.app.core.config import ROOT, load_settings
from backend.app.database.session import create_database
from backend.app.services.recordings import claim_job, complete_job, fail_job, heartbeat, recover_stale_jobs


logger = logging.getLogger(__name__)


def probe_video(path):
    result = subprocess.run([sys.executable, "-m", "services.recording_engine.probe", str(path)],
                            cwd=ROOT, capture_output=True, timeout=30, check=True)
    return json.loads(result.stdout)


def build_command(source, output, segment_seconds, threads):
    executable = os.getenv("FFMPEG_EXE") or shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
    return [executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-xerror",
            "-protocol_whitelist", "file,pipe", "-threads", str(threads), "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1", "-map_chapters", "-1",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", str(threads),
            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-pix_fmt", "yuv420p", "-bf", "0",
            "-force_key_frames", f"expr:gte(t,n_forced*{segment_seconds})",
            "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000",
            "-f", "segment", "-segment_time", str(segment_seconds), "-segment_time_delta", "0.05", "-reset_timestamps", "1",
            "-segment_format", "mp4", "-segment_format_options", "movflags=+faststart",
            "-segment_list", str(output / "segments.csv"), "-segment_list_type", "csv",
            "-progress", str(output / "progress.txt"), "-stats_period", "2",
            str(output / "segment-%05d.mp4")]


def read_progress(path, duration):
    if not path.exists():
        return 0
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 8192))
        lines = handle.read().decode("utf-8", errors="replace").splitlines()
    processed = 0
    for line in lines:
        if line.startswith("out_time_us="):
            try:
                processed = max(processed, int(line.split("=", 1)[1]) / 1_000_000)
            except ValueError:
                pass
    return 100 * processed / duration


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def transcode(engine, job, settings, output, duration, stopping):
    source = settings["storage"] / job["id"] / "source"
    command = build_command(source, output, job["segment_seconds"], settings["ffmpeg_threads"])
    started = time.monotonic()
    last_heartbeat = 0
    error_log = output / "ffmpeg-error.log"
    with error_log.open("wb") as errors:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=errors)
        try:
            while process.poll() is None:
                if stopping.is_set():
                    raise InterruptedError("Worker stopping")
                if time.monotonic() - started > settings["job_timeout_seconds"]:
                    raise TimeoutError("Processing time limit exceeded")
                if shutil.disk_usage(settings["storage"]).free < settings["min_free_bytes"]:
                    raise OSError("Insufficient storage")
                if error_log.stat().st_size > 1024 * 1024:
                    raise RuntimeError("Media processing failed")
                if time.monotonic() - last_heartbeat >= 5:
                    progress = read_progress(output / "progress.txt", duration)
                    if not heartbeat(engine, job, progress, duration):
                        raise RuntimeError("Worker lease lost")
                    last_heartbeat = time.monotonic()
                stopping.wait(0.2)
            if process.returncode != 0:
                raise RuntimeError("FFmpeg rejected the input")
        finally:
            stop_process(process)


def collect_segments(engine, job, settings, output, duration):
    rows = []
    with (output / "segments.csv").open(newline="", encoding="utf-8") as listing:
        entries = list(csv.reader(listing))
    if not entries:
        raise ValueError("No segments generated")
    for number, entry in enumerate(entries, start=1):
        filename, start, end = entry
        path = output / Path(filename).name
        if not path.is_file() or path.suffix != ".mp4":
            raise ValueError("Invalid segment manifest")
        if not heartbeat(engine, job, 99, duration):
            raise RuntimeError("Worker lease lost")
        info = probe_video(path)
        rows.append({"id": str(uuid4()), "video_id": job["id"], "number": number,
                     "start_seconds": float(start), "end_seconds": float(end),
                     "duration_seconds": info["duration_seconds"], "bytes": path.stat().st_size,
                     "relative_path": path.relative_to(settings["storage"]).as_posix()})
    return rows


def process_job(engine, job, settings, stopping=None):
    stopping = stopping or Event()
    output = settings["storage"] / job["id"] / job["lease_token"]
    published = False
    publication_started = False
    try:
        output.mkdir(parents=True, exist_ok=False)
        source = settings["storage"] / job["id"] / "source"
        info = probe_video(source)
        duration = info["duration_seconds"]
        if not heartbeat(engine, job, 0, duration):
            raise RuntimeError("Worker lease lost")
        transcode(engine, job, settings, output, duration, stopping)
        rows = collect_segments(engine, job, settings, output, duration)
        publication_started = True
        complete_job(engine, job, rows, duration)
        published = True
        logger.info("Recording %s ready: %s segments", job["id"], len(rows))
        return True
    except Exception as error:
        logger.error("Recording %s failed (%s)", job["id"], type(error).__name__)
        fail_job(engine, job, "Processing failed. Check media validity, free storage and worker configuration, then retry.")
        return False
    finally:
        # A lost DB connection during commit has an ambiguous outcome; retain files.
        if not published and not publication_started and output.exists():
            root = settings["storage"].resolve()
            target = output.resolve()
            if target.is_relative_to(root) and target != root:
                shutil.rmtree(target)


def main():
    parser = argparse.ArgumentParser(description="Durable recording segmentation worker")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    engine = create_database(settings["database_url"])
    stopping = Event()

    def request_stop(signum, frame):
        stopping.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        while not stopping.is_set():
            try:
                recover_stale_jobs(engine)
                job = claim_job(engine)
                if job:
                    process_job(engine, job, settings, stopping)
                elif not args.once:
                    stopping.wait(2)
            except Exception as error:
                logger.error("Worker cycle failed (%s); retrying", type(error).__name__)
                stopping.wait(5)
            if args.once:
                break
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
