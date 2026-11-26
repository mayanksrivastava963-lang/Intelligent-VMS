import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import torch

from .detection.detector import ObjectDetector


def benchmark(device="cuda", iterations=50, warmup=10):
    if iterations < 1 or warmup < 1:
        raise ValueError("Iterations and warmup must be positive")
    detector = ObjectDetector(device=device)
    frame = np.random.default_rng(42).integers(0, 256, (720, 1280, 3), dtype=np.uint8)
    using_cuda = detector.device.type == "cuda"
    for _ in range(warmup):
        detector.detect(frame)
    if using_cuda:
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
    timings = []
    gpu_timings = []
    for _ in range(iterations):
        if using_cuda:
            start = torch.cuda.Event(enable_timing=True)
            end = torch.cuda.Event(enable_timing=True)
            start.record()
        before = perf_counter()
        detector.detect(frame)
        if using_cuda:
            end.record()
            torch.cuda.synchronize()
            gpu_timings.append(start.elapsed_time(end))
        timings.append((perf_counter() - before) * 1000)
    result = {
        "input": "synthetic seeded noise, 1280x720 BGR; no accuracy evaluation",
        "device": str(detector.device),
        "model_parameter_device": str(next(detector.model.parameters()).device),
        "torch": torch.__version__, "cuda_runtime": torch.version.cuda,
        "iterations": iterations, "warmup": warmup,
        "mean_detection_ms": float(np.mean(timings)),
        "p50_detection_ms": float(np.percentile(timings, 50)),
        "p95_detection_ms": float(np.percentile(timings, 95)),
        "serial_detection_fps": 1000 / float(np.mean(timings)),
    }
    if using_cuda:
        result.update({"gpu": torch.cuda.get_device_name(),
                       "mean_cuda_event_span_ms": float(np.mean(gpu_timings)),
                       "peak_allocated_mib": torch.cuda.max_memory_allocated() / 1024**2,
                       "peak_reserved_mib": torch.cuda.max_memory_reserved() / 1024**2})
    return result


def main():
    parser = argparse.ArgumentParser(description="Synthetic end-to-end detector benchmark")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = benchmark(args.device, args.iterations, args.warmup)
    report = json.dumps(result, indent=2)
    print(report)
    if args.output:
        args.output.write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
