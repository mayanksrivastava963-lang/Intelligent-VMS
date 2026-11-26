# Recording upload workspace

This module accepts a local video from a React/TypeScript browser interface,
persists the upload, queues a durable database job, and creates independently
playable H.264/AAC MP4 files in 30-minute intervals. The final file holds the
remainder. Video bytes live on disk; database rows contain recording and segment
metadata. No AI model is imported by the API or recording worker.

## Run locally on Windows

From the repository root, using the existing Python 3.12 AI virtual environment:

```powershell
.\services\ai_engine\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
npm.cmd --prefix frontend ci
.\services\ai_engine\.venv\Scripts\python.exe scripts/run_recordings.py
```

Configure `VMS_OPERATOR_USERNAME`, `VMS_OPERATOR_PASSWORD_HASH`, and
`VMS_SESSION_SECRET` in the ignored local `.env` file. Password hashes use
PBKDF2-SHA256; do not commit `.env`. If no credentials are configured, the
launcher asks for an Admin ID and password. It starts the API and separate
recording worker. In another terminal run `npm.cmd --prefix frontend run dev`,
open **http://127.0.0.1:5173**, and sign in. API documentation is available at
**http://127.0.0.1:8000/docs**. Ctrl+C stops each terminal's process. Restarting with a new session secret invalidates
old browser sessions, not recordings.

Without database configuration, local development uses
`storage/recordings.db` (SQLite/WAL). This is a local fallback, not a production
PostgreSQL verification. Uploads/segments are under `storage/recordings` unless
`RECORDING_STORAGE_PATH` overrides it. The existing `.env` is read, never rewritten.

For frontend development, run `npm.cmd --prefix frontend run dev` alongside the
API and worker; Vite forwards `/api` to port 8000. The backend does not serve the
frontend; production hosting requires a separate frontend server and API proxy.

## PostgreSQL and Docker deployment

Set the existing PostgreSQL variables and the new secret variables in your
untracked `.env` or deployment secret manager. Use different, strong values for
the operator password and session secret; the secret needs at least 32 random
characters. Never use test passwords outside isolated tests.

```powershell
docker compose -f docker-compose.yml -f docker-compose.recordings.yml up --build -d postgres recording-init recording-api recording-worker
```

The override uses PostgreSQL, a shared persistent `recording_data` volume, an
initialization step before API/worker startup, a non-root application image,
restart policies and bounded worker CPU/memory. Credentials are passed as separate
configuration fields, so passwords containing URL-reserved characters work.
Database initialization creates the initial tables; it does **not** migrate
existing column definitions. Introduce reviewed, versioned Alembic migrations
before changing this deployed schema.

The base Compose file's PostgreSQL volume is unchanged. API is bound only to
localhost. Before external access, add an HTTPS reverse proxy, set
`VMS_SECURE_COOKIE=true`, configure upload/body/idle timeouts for large files and
disable proxy request buffering for the upload route. Add shared authentication
rate limiting at the proxy for multiple API replicas. Do not directly expose the
development HTTP server to the internet.

For native PostgreSQL, set `RECORDING_DATABASE=postgres` and `POSTGRES_HOST`,
`POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`; the configured
role must already have access to that database. Alternatively set a complete
`DATABASE_URL`. A supplied DATABASE_URL takes precedence.

## How the code is organized

- [FastAPI application](../backend/app/main.py): operator session, authenticated
  upload/list/detail/retry/playback endpoints, upload limits and same-origin UI.
- [Configuration](../backend/app/core/config.py): storage, secrets and resource limits.
- [Tables](../backend/app/models/recordings.py): recording and segment metadata.
- [Camera operations](../backend/app/services/recordings.py): named virtual
  camera registration, status changes and removal without deleting source video.
- [Database setup](../backend/app/database/session.py): PostgreSQL/SQLite engines.
- [Job operations](../backend/app/services/recordings.py): atomic claims, lease
  heartbeats, stale-job recovery and transactional result publication.
- [Worker](../services/recording_engine/worker.py): probe, encode, validate and publish.
- [Media probe](../services/recording_engine/probe.py): isolated PyAV metadata
  inspection, called with a subprocess timeout.
- [React workspace](../frontend/src/App.tsx): sign-in, drag/drop and batch file upload,
  upload progress/cancellation, job polling, searchable paginated library,
  retry controls, a multi-camera grid and independent virtual feed controls.
- [API client](../frontend/src/api.ts): same-origin fetch and streamed XHR uploads.

Only modest dictionaries/functions are used for backend application state.
SQLAlchemy Core tables avoid an unnecessary ORM object hierarchy. A FastAPI app
factory provides independent settings and databases for tests.

## Processing and storage contract

1. Authenticate; choose one supported file (MP4/MOV/MKV/AVI/WEBM/M4V).
2. Stream raw bytes to a server-generated UUID directory, never a filename-derived
   path. Actual bytes and available disk space are checked while writing.
3. Atomically rename the completed source and mark its row `queued`.
4. A separate worker claims the row. PostgreSQL uses `FOR UPDATE SKIP LOCKED`;
   a conditional update and unique lease token fence competing workers.
5. Probe in a child process (30-second timeout). Require a video stream, known
   duration up to 48 hours, and bounded resolution. Invalid files become failed jobs.
6. Re-encode with forced keyframes and segment at 1,800 seconds. This costs CPU
   but avoids waiting for arbitrary source keyframes and produces browser-compatible
   playback. The original source is retained unmodified. Output is a lossy transcode,
   not a bit-identical evidence copy. Metadata/chapters are stripped from output.
7. Probe every generated segment, then atomically insert all metadata and mark
   the recording `ready`. Partial segments are never exposed by the playback API.

Segment start/end values are media timeline seconds from FFmpeg's manifest;
container duration is also stored separately. Boundaries are constrained by frame
timestamps and audio encoder delay. `segment_time_delta=0.05` handles small
keyframe rounding errors; real footage may vary by approximately a frame/audio
packet around nominal boundaries. No interval of footage is intentionally dropped.
See [FFmpeg's segment documentation](https://ffmpeg.org/ffmpeg-formats.html#segment_002c-stream_005fsegment_002c-ssegment).

The worker encodes one job at a time with two FFmpeg threads by default. It
heartbeats every five seconds, has a configurable 24-hour job timeout, checks
free disk space, and terminates FFmpeg on stop/error. Stale processing leases
older than 90 seconds are queued again, with at most three automatic attempts.
Manual retry resets the attempt counter. Interrupted uploads expire after one
hour without updates. Worker recovery runs only while a worker is running.

Failed current attempts are removed after the child exits; originals remain for
retry. A hard process/host crash can leave orphan attempt folders or partial
uploads. Automatic retention/orphan cleanup is **not yet implemented**. Monitor
storage and reconcile these during maintenance with the worker stopped; never
delete active worker directories. Back up database and storage together.

## API

All recording endpoints require the signed HttpOnly session cookie. Every write
requires `X-VMS-Request: 1`; cross-origin CORS access is not enabled.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/auth/login` | JSON password; eight-hour session |
| GET | `/api/auth/session` | Session and upload configuration |
| POST | `/api/auth/logout` | Clear browser session |
| POST | `/api/videos` | Raw video body, URL-encoded `X-Filename`; returns 202 |
| GET | `/api/videos?limit=50&offset=0` | Paginated metadata, maximum 100 rows |
| GET | `/api/videos/{id}` | Recording and segment metadata |
| POST | `/api/videos/{id}/retry` | Requeue a failed job with an existing source |
| GET | `/api/cameras` | List registered virtual cameras and playable segments |
| POST | `/api/cameras` | Register a ready recording as a virtual camera |
| POST | `/api/cameras/{id}/start` | Mark a virtual camera running |
| POST | `/api/cameras/{id}/stop` | Stop a virtual camera |
| POST | `/api/cameras/{id}/restart` | Restart playback from the first segment |
| DELETE | `/api/cameras/{id}` | Remove a camera registration; retain source video |
| GET | `/api/segments/{id}/content` | Authenticated MP4, single-byte-range support |
| GET | `/api/health` | API/database readiness, not worker health |

## Virtual camera dashboard

Select a ready recording and add it as a virtual camera with a display name and
location. Camera registrations have UUIDs, persist in the configured database,
and are independent of recording rows: deleting a camera does not delete the
uploaded source or its segments. The React monitor lays feeds out responsively;
each card can start, stop, restart, loop, expand to fullscreen or be removed.
Video plays from the recording's browser-compatible MP4 segments in order.
Multiple files selected in the upload picker are uploaded sequentially.

These are **browser-played virtual feeds**, not server-published RTSP streams.
The `running`/`stopped` status records the operator's requested state and is not
a camera health check. Physical RTSP/ONVIF connectivity, server-side streaming,
camera credential storage, persistent playback position and feed reconnection
are not implemented yet. AI detection controls and overlays are also not
connected to this dashboard; the existing detector remains a separate milestone.

Filename-extension checks are only an initial filter; the worker verifies media.
Clients never receive filesystem paths or raw FFmpeg/database exception messages.
Playback uses FileResponse's HTTP range support for seeking. It rejects multi-range
requests. The UI cancels in-flight uploads, not already queued processing jobs.

## Verification

```powershell
.\services\ai_engine\.venv\Scripts\python.exe -m pytest backend/tests services/ai_engine/tests -q
npm.cmd --prefix frontend run build
```

Tests generate synthetic media, run real FFmpeg, use isolated SQLite databases
and authenticate through the actual FastAPI routes. Coverage includes:

- Unauthorized requests, request-protection header and login throttling.
- Upload size/extension/empty-body validation and sanitized filenames.
- Corrupt-media failure without publishing segments; retry state restrictions.
- Audio-preserving 2-second segmentation and a final remainder.
- A real **3,605-second video -> 1,800 + 1,800 + 5 seconds**.
- Short videos, authenticated HTTP 206 playback, single-range restrictions.
- Job claim exclusivity, stale lease recovery and old-worker fencing.
- Worker stop cleanup without publishing partial output.
- Virtual camera creation from a ready recording, start/restart/stop, deletion,
  and verification that source recording data remains intact.

Browser QA also exercised sign-in, upload, status polling, segment selection and
actual HTML video playback, plus a 390-pixel viewport overflow check. QA data is
isolated under ignored `storage/recording-qa`, not production storage.

## Deployment limits and next work

This is a tested upload-to-recording workflow, not a certified production VMS.
Docker/PostgreSQL execution has not been verified on this workstation because
those tools/services are unavailable. Live RTSP/ONVIF ingestion is not implemented
by this module. AI code and continuous-camera recording are separate concerns.

Before company deployment: verify Docker/PostgreSQL on the target server, test
representative authorized CCTV codecs/VFR/audio synchronization, load-test large
uploads and concurrent workers, validate backups/recovery and storage retention,
add multi-user RBAC/audit logging and shared rate limiting, configure TLS and
monitoring, and review FFmpeg/codec distribution licensing. Uploads are not
resumable and there is no retention/delete workflow yet. SQLite is for a single
local worker; use PostgreSQL for concurrent production workers.

Next functional milestone: independent live RTSP recorder with camera-specific
reconnection, segment finalization, health reporting and recording retention.
