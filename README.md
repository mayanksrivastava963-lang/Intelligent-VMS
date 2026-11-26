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

## AI engine

### RTSP camera preview

In **Live view**, choose **Add RTSP camera**, enter a name, location and the
authorized `rtsp://` URL, then start the feed. The backend decodes RTSP over TCP
and sends a browser-compatible MJPEG preview. Each viewer creates a separate
camera connection and decoder; CPU and bandwidth grow with viewers.
The preview samples up to 10 frames per second and does not record the stream.
The UI reports connecting until frames arrive; a started camera is a requested
state, not a guarantee that the camera is online. It retries failed connections.

RTSP addresses are encrypted in the database using a key derived from
`VMS_SESSION_SECRET`; keep that secret stable and backed up. Changing it makes
previously saved camera addresses unreadable and requires re-adding them. URLs
are excluded from camera API responses. Physical CCTV and RTSP transport testing
remain pending until a camera or simulated RTSP server is available.

Local detection and tracking are separate from recording. See the
[AI engine documentation](services/ai_engine/README.md).

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
