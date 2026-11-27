# Observed Performance & Sizing Benchmarks — 0.1.0-rc3 (2026-11-27)

**Maximum tested simultaneous production-server capacity: NOT YET ESTABLISHED.**

Do not treat laptop development constraints (16 GiB RAM, 4 GiB VRAM) as an application limit. All worker concurrency, DB pool sizes, memory/CPU caps, and resource thresholds (`VMS_RESOURCE_WARN=75`, `VMS_RESOURCE_REDUCE=80`, `VMS_RESOURCE_BLOCK=85`) are externally configurable.

## Measured Baselines

1. **Isolated Metadata Query Benchmark (`scripts/benchmark_metadata.py`):**
   Measured 25 iterations of `list_rtsp_cameras` on local SQLite (0 active RTSP streams):
   - 4 cameras: median `0.151 ms`, p95 `0.250 ms`
   - 64 cameras: median `0.283 ms`, p95 `0.493 ms`
   - 256 cameras: median `0.789 ms`, p95 `1.010 ms`
2. **Short Laptop 4-Stream Smoke Run (RC1 runtime):**
   Four `320x180 @ 5 fps` `256 kbps` streams hit host RAM cutoff (`89.2% -> 90.6%`) at `49.4s`. Not a sustained pass.
3. **Production Server Progressive & Soak Tooling Ready:**
   Use `scripts/progressive_load_test.py` on the target server to benchmark `4 -> 8 -> 16 -> 32 -> 48 -> 60+` cameras and 2h/8h/24h/72h soaks while capturing CPU, RAM, GPU, VRAM, disk throughput, API p95 latency, recording gaps, and frame freshness. See [HARDWARE_SIZING_GUIDE.md](HARDWARE_SIZING_GUIDE.md) and [RESOURCE_VALIDATION.md](RESOURCE_VALIDATION.md).
