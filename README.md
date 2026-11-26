# Intelligent VMS

Video management services with an independent recording pipeline and AI engine.

## Recording workspace

The React + FastAPI workspace supports authenticated video uploads, durable
background processing, 30-minute MP4 segmentation, recording metadata and
browser playback. A final short segment retains the remainder.

```powershell
.\services\ai_engine\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
npm.cmd --prefix frontend ci
.\services\ai_engine\.venv\Scripts\python.exe scripts/run_recordings.py
```

In a second terminal, run `npm.cmd --prefix frontend run dev` and open
http://127.0.0.1:5173 for the dashboard. The backend only serves APIs and Swagger
at http://127.0.0.1:8000/docs. Swagger UI loads its assets from a CDN.

Sign in with your configured account. Local startup uses the PostgreSQL settings
in `.env` when `RECORDING_DATABASE=postgres` is selected; otherwise it uses SQLite.
See [recording setup, API, tests and deployment limitations](docs/recording-workspace.md).

After signing in, use **Cameras** to monitor virtual feeds together. Select a
ready recording under **Recordings**, choose **Add as virtual camera**, and give
it a camera name and location. The dashboard stores that camera separately from
its source recording and supports independent start, stop, restart, loop,
fullscreen and remove controls. The upload picker accepts multiple files and
uploads them one at a time. See the camera API and limitations in the
[recording workspace guide](docs/recording-workspace.md#virtual-camera-dashboard).

## RTSP camera preview and recording

In **Live view**, choose **Add RTSP camera** and provide its name, location,
main `rtsp://` URL and optional low-bandwidth substream URL. MediaMTX pulls
each started source over TCP and serves authenticated same-origin LL-HLS to
the grid. A grid page contains at most 9 or 16 players. Fullscreen switches
from the substream to the main stream; the WebRTC button opens a low-latency
view. Nginx checks the existing session and `camera.read` permission before
proxying every playlist, media part or WebRTC request. MediaMTX HTTP and
Control API ports are only available inside the Docker network.

The separate RTSP recorder runs FFmpeg stream-copy jobs independently of the
browser and AI worker. Completed MP4 segments appear in the playback library.
The retention worker prunes completed RTSP recordings after the configured
age or at low disk space, without deleting active recording run directories.
Some camera codecs cannot be remuxed to browser-compatible MP4 without
transcoding; validate each camera's codec before deployment.

Local development without `MEDIAMTX_API_URL` retains the bounded shared MJPEG
preview, with one Uvicorn worker. The Docker stack uses MediaMTX and supports
multiple API workers. Camera sources stored in the database use Fernet
encryption; keep `VMS_SESSION_SECRET` stable and backed up. API responses never
return source URLs or camera passwords. Physical camera validation remains
pending until authorized hardware is available.

## AI engine

Each camera card has **Enable AI** / **Disable AI**. The switch is persistent.
The optional `ai-worker` samples enabled RTSP cameras, keeps only each camera's
latest frame, performs bounded batched Torch inference, tracks objects separately
per camera and stores recent overlays in Redis. Intrusion, loitering and
unattended-object evaluators create reviewable alerts. Operators can see alerts;
users with `alerts.manage` can acknowledge them. Intrusion zones are optional
per-camera pixel polygons in `AI_INTRUSION_ZONES`. Detection is advisory and
does not classify any person as a threat. Virtual cameras still use local
authenticated JPEG sampling. Video and recording continue if AI fails.

See [60-camera deployment and benchmark guide](docs/scaling-60-cameras.md)
and [AI engine documentation](services/ai_engine/README.md).

## Validation

```powershell
.\services\ai_engine\.venv\Scripts\python.exe -m pytest backend/tests services/ai_engine/tests -q
```

The Docker engine was unavailable during this implementation pass. Container
deployment, actual RTSP playback, 60-camera load and physical CCTV are not
verified. Do not treat this repository as a production-certified CCTV system.

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for current implementation progress,
validation results and known limitations.

## Dashboard and system resources

The **Overview** page links to the camera wall and playback library. **Live view**
supports camera/location search, running/stopped filters, and automatic or
1–4-column layouts (smaller screens use fewer columns). All navigation remains
available on mobile screens.

Accounts with `health.read` permission can open **System health** for actual
CPU utilization, RAM used/available, recording-volume disk space, host uptime,
API uptime and API process memory. The dashboard fetches `/api/system/metrics`
every five seconds. CPU is sampled over 150 ms; readings are shared through a
three-second backend cache. CPU and RAM cover the backend host, and disk usage
covers the entire volume containing recordings, not only VMS files.

CPU/RAM charts retain up to 60 samples in the current viewing session. A failed
refresh is visibly marked; the last successful values are not presented as live.
GPU telemetry, long-term monitoring history and capacity benchmarking are not
included in this monitor. Monitoring never reads or uploads video contents.
