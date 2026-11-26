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

## RTSP camera preview

In **Live view**, choose **Add RTSP camera**, enter a name, location and the
authorized `rtsp://` URL, then start the feed. One backend process opens one
RTSP decoder per camera and shares its latest JPEG frame with authorized
dashboard viewers. The preview samples up to 10 frames per second and does not
record the stream. The backend reports connecting, online, reconnecting, or
offline from decoder activity and frame freshness. A started camera is only a
requested state. Connections retry after failures. Stopping or removing a
camera closes its shared acquisition independently of other cameras.

Run the API with one Uvicorn worker for this local in-memory stream hub. A
multi-process deployment needs an external shared streaming service such as
MediaMTX and separate access controls. The current MJPEG preview is intended
for local development and is not a production streaming architecture.

RTSP addresses are encrypted in the database using a key derived from
`VMS_SESSION_SECRET`; keep that secret stable and backed up. Changing it makes
previously saved camera addresses unreadable and requires re-adding them. URLs
are excluded from camera API responses. Physical CCTV and RTSP transport testing
remain pending until a camera or simulated RTSP server is available.

## AI engine

Each camera card has **Enable AI** / **Disable AI**. The switch is stored in
the database. While an enabled camera is playing, the browser sends a reduced
JPEG frame to the authenticated API every two seconds by default. One shared
SSDLite detector processes a bounded sample at a time; fresh detections are
drawn briefly over the matching video frame with class, confidence and object
count. Set `AI_SAMPLE_INTERVAL_MS` in `.env` to change the sampling interval
(minimum 1000 ms). Paused feeds do not send samples. An AI failure is shown on
the tile and does not stop video playback.

This initial dashboard inference requires the Python environment to contain
the dependencies in `services/ai_engine/requirements.txt` and cached model
weights. The lightweight backend Docker image currently lacks PyTorch and
OpenCV, so its AI endpoint returns unavailable. Dashboard AI sampling only
runs while that dashboard is open; background AI analytics and recording are
separate milestones. See the [AI engine documentation](services/ai_engine/README.md).

## Validation

```powershell
.\services\ai_engine\.venv\Scripts\python.exe -m pytest backend/tests services/ai_engine/tests -q
```

Live-camera recording, retention and production
deployment validation remain separate milestones. Do not treat this repository
as a production-certified CCTV system.

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
