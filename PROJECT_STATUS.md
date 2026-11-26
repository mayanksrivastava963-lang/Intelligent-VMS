# Intelligent-VMS Project Status

Last updated: 2026-11-26
Current branch: `feature/ai-engine`

## Implemented

- Argon2id account authentication, revocable HttpOnly `SameSite=strict`
  sessions, `X-VMS-Request: 1` write protection, role permissions, and audit
  logs remain in place. RTSP main/substream URLs are Fernet-encrypted in the
  database and excluded from camera API responses and errors.
- Video upload, background AVI/MP4 conversion, virtual cameras, browser
  playback, recording search and independent virtual camera controls remain.
  Prior local testing included the supplied AVI and synthetic MP4/AVI footage.
- RTSP cameras can be added from the UI with optional low-bandwidth substream.
  In the Docker stack, MediaMTX provisions each running path once and serves
  LL-HLS and WebRTC through session-protected Nginx routes. The camera grid
  renders at most 9 or 16 media players per page. Fullscreen selects the main
  stream. A one-worker local MJPEG fallback remains for development.
- Camera listing batches segment lookup into two queries instead of one per
  camera. `/api/cameras` and `/api/videos` accept limit/offset. Camera status
  reads use one MediaMTX path-list request per page.
- PostgreSQL pool size, overflow and recycle settings are explicit. Alembic
  baselines the recording/auth schema and migrates RTSP health, encrypted
  substream and alert columns/tables. Login rate limiting uses Redis when
  configured and a locked local fallback for isolated tests.
- A separate FFmpeg RTSP recorder stream-copies each running camera into MP4
  segments and publishes completed segments to the existing playback library.
  A separate retention service prunes completed RTSP files by age and disk
  free-space policy while skipping active recording runs.
- A separate optional GPU AI worker samples enabled cameras, keeps one pending
  frame per camera, performs bounded batched SSDLite inference, tracks objects
  per camera and saves intrusion, loitering and unattended-object alerts for
  review. The UI shows overlays and alerts; `alerts.read` and `alerts.manage`
  gate the alert APIs.
- Nginx and Docker Compose configurations, a CUDA AI worker image, and a
  synthetic 60-camera benchmark script are present.

## Validation observed this pass

- Backend and AI pytest suite: **77 passed** in the final regression run.
  Focused recorder, retention, MediaMTX provisioning, query-count and Alembic
  tests passed with synthetic fixtures.
- TypeScript `tsc --noEmit` and Vite production build passed after the final
  changes. `hls.js` loads in a separate chunk; Vite reports its size warning.
- Combined Compose files with `ai` and `production` profiles passed
  `docker compose config --quiet` using placeholder environment values.
- Existing PostgreSQL and supplied AVI playback had passed in a prior local
  phase. This scaling pass used temporary SQLite databases and synthetic media;
  it did not modify the existing company PostgreSQL database or footage.

## Unverified and remaining work

- Docker Desktop's Linux engine was unavailable on this development machine.
  MediaMTX config validation, Nginx TLS access, container image builds,
  actual FFmpeg/MediaMTX transport, continuous recorder operation, GPU worker
  execution and 60-camera streaming could not be run here.
- **No measured 60-camera CPU, RAM, VRAM, FPS, disk throughput or API-latency
  numbers are available.** The benchmark script is ready for a high-resource
  server but has not been executed. Query-count tests do not establish 60-feed
  capacity.
- Physical CCTV and ONVIF hardware testing remain pending. Simulated RTSP is
  not equivalent to physical camera validation.
- The AI worker defaults to at most four enabled RTSP cameras. Raising
  `AI_MAX_CAMERAS` to 60 needs server-side GPU/CPU/VRAM measurements. Intrusion
  zones require configuration. Current unattended-object logic is an advisory
  tracker rule, not a validated safety decision.
- FFmpeg stream-copy to MP4 depends on camera codecs and keyframes. Test each
  camera model; incompatible codecs may require transcoding. Long-term
  recorder continuity, retention under disk pressure, HA/failover and disaster
  recovery are not yet validated.
- Run a security/access test against real Nginx and MediaMTX before making
  the service reachable to operators. Supply trusted TLS certificates and set
  `VMS_SECURE_COOKIE=true`. Pin and validate container image versions for the
  production server after the Docker engine is available.

See [60-camera deployment and benchmark guide](docs/scaling-60-cameras.md)
for commands, assumptions, configuration and validation steps.
