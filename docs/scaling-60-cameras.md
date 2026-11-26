# Multi-camera server deployment and verification

This architecture is designed to be benchmarked with 60 RTSP cameras. The
number is a target, **not a verified capacity claim**. Camera bitrate, codec,
resolution, keyframe interval, number of viewers, GPU and storage speed all
change the practical limit.

## Data path

1. FastAPI stores encrypted camera URLs and asks MediaMTX's private Control API
   to add or remove source paths. MediaMTX pulls main and optional substreams
   over TCP. RTSP credentials do not appear in browser responses.
2. Nginx serves `frontend/dist` over HTTPS. `/live/*` and `/live-webrtc/*`
   first call `/api/stream-access`, which checks the signed, revocable HttpOnly
   session, `camera.read` permission and camera state. Nginx then streams
   HLS/WebRTC directly from MediaMTX. The MediaMTX HTTP/Control API ports are
   not published on the host. Containers on the private Compose network are
   trusted infrastructure.
3. A separate recorder pulls each running camera path from MediaMTX with FFmpeg
   stream copy. Completed MP4 files become recording/segment rows. A separate
   retention worker prunes completed RTSP recordings by age and free-space
   limits. Both continue when all browsers close.
4. The optional AI worker samples enabled cameras and overwrites stale pending
   frames per camera. One model performs batches of up to eight. Redis holds
   recent overlays; PostgreSQL holds alerts. API workers do not load the model.

## Server setup

Copy `.env.example` to `.env` and set strong PostgreSQL, operator, MediaMTX API
and session secrets. Do not commit `.env`. Set `VMS_SECURE_COOKIE=true` for
HTTPS. Set `VMS_PUBLIC_HOST` to a reachable server IP or DNS name for WebRTC
ICE. Place a valid TLS certificate and key at
`infrastructure/nginx/tls/fullchain.pem` and `privkey.pem`; this directory is
ignored by Git. Keep PostgreSQL, Redis and MediaMTX on a trusted private Docker
network. Only Nginx ports 80/443 and WebRTC UDP 8189 are public. Use network
firewall rules as well as the Compose port bindings.

```powershell
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
docker compose -f docker-compose.yml -f docker-compose.recordings.yml --profile production up -d --build
```

The `recording-init` container applies Alembic migrations before the API,
recorder and retention workers start. Back up the existing database and footage
before using a new deployment. Default API worker count is four, with a pool
of five PostgreSQL connections and up to five overflow connections per worker.
Account for every additional process when sizing PostgreSQL `max_connections`.
Use `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` and `VMS_API_WORKERS` to tune measured load.

To enable GPU inference on a server with an NVIDIA driver and container
toolkit, add `--profile ai` before `up`. The AI image installs the official
PyTorch 2.11 / Torchvision 0.26 CUDA 12.8 wheels. `AI_BATCH_SIZE`,
`AI_SAMPLE_INTERVAL_MS` and `AI_MAX_CAMERAS` bound GPU and decoder load. The
default `AI_MAX_CAMERAS=4` protects a small laptop GPU. Raise it gradually on
the server only after measuring VRAM, inference time and dropped samples.
Intrusion zones can be set with `AI_INTRUSION_ZONES` as a JSON object mapping
camera UUIDs to pixel-coordinate polygons. Loitering and unattended-object
thresholds remain configurable in seconds.

Optional low-bandwidth RTSP substreams should use H.264 at a lower resolution
and bitrate. The grid uses a provided substream; fullscreen and the WebRTC
view use the main stream. Without a substream, the grid also pulls the main
stream. Browser codec support and RTSP camera keyframe spacing must be tested
with the actual camera models. FFmpeg stream copy requires codecs that can be
remuxed into MP4; incompatible camera codecs need a separate transcoding plan.

## Synthetic benchmark

The host Docker engine must be running. The benchmark override binds RTSP
ingest to localhost only and accepts publishing on names `benchmark-0` through
`benchmark-59`. Do not enable this override on an untrusted host. Run the
normal stack with the override added, then run the script with a dedicated
benchmark account authorized to manage cameras. Use a real trusted HTTPS
certificate for the API URL.

```powershell
docker compose -f docker-compose.yml -f docker-compose.recordings.yml -f docker-compose.benchmark.yml --profile production --profile ai up -d --build
$env:VMS_BENCHMARK_USERNAME = 'admin'
$env:VMS_BENCHMARK_PASSWORD = '<benchmark-account-password>'
.\services\ai_engine\.venv\Scripts\python.exe scripts/benchmark_60_cameras.py --run --count 60 --duration 120 --api https://your-vms-host
```

The script creates 60 synthetic low-resolution FFmpeg publishers, registers
them as RTSP cameras, checks URL leakage, polls the API with 16 concurrent
clients, reports online count, API latency, host CPU/RAM, publisher FPS and
available NVIDIA GPU readings, then removes its cameras and stops publishers.
It does not use company footage. Synthetic 160x90 at 5 FPS is an infrastructure
smoke test, not a substitute for 60 production bitrate streams or 60 AI-enabled
streams. Also measure container CPU/RAM, network throughput, disk write rate,
PostgreSQL connections, MediaMTX latency, and 24-hour recording continuity
on the target server. Test camera failure/reconnect and Nginx access rejection.

## Current validation boundary

Local pytest, Vite build and Compose configuration parsing pass. Docker Desktop
was unavailable during this work, so the MediaMTX config, Nginx TLS behavior,
container image builds, real RTSP transport, GPU worker, recorder continuity
and the 60-camera benchmark have not been executed end to end. Physical CCTV
hardware also remains unavailable. Do not present those as verified results.

Configuration syntax was based on the [MediaMTX configuration reference](https://github.com/bluenviron/mediamtx/blob/main/mediamtx.yml)
and the [official PyTorch installation matrix](https://pytorch.org/get-started/previous-versions/).
