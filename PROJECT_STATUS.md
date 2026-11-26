# Intelligent-VMS Project Status

Last updated: 2026-11-26
Current branch: `feature/ai-engine`

## Completed in the current workspace

- Authenticated local video upload with extension/size checks and UUID storage.
- Background FFmpeg processing into browser-compatible MP4 segments.
- Recording list, detail, retry and authenticated playback endpoints.
- Persistent virtual camera registrations for processed recordings.
- Responsive multi-camera dashboard with per-feed start, stop, restart, looping,
  fullscreen and removal controls.
- Multi-file selection uploads files sequentially.
- Camera removal preserves the underlying video and segments.
- PostgreSQL-backed users, built-in roles and permissions, Argon2id password
  hashes (with legacy PBKDF2 upgrade), revocable eight-hour HTTP-only sessions,
  and sign-in/user-management audit events.
- Administrator UI pages for Users, Roles & Permissions, and Audit Logs.
- Redesigned overview, consistent navigation and mobile layout; camera search,
  status filters, selectable grid columns, and upload access across viewing pages.
- Permission-protected CPU/RAM/disk metrics with five-second frontend refresh,
  live session trends, host/API uptime and API memory. Failed updates show a
  stale-data warning. No GPU telemetry or historical metrics database is claimed.
- Backend permission checks for user, camera, and recording APIs; user responses
  exclude password hashes.
- AVI probing derives runtime from packet timestamps when container and stream
  duration headers are missing.

## Validation run

- `python -m pytest backend/tests/test_recordings.py -q` using the existing
  Python 3.12 AI environment: **17 passed** (including metrics authorization,
  real readings, caching and monitoring failure isolation).
- `python -m pytest backend/tests services/ai_engine/tests -q` using the
  existing Python 3.12 AI environment: **57 passed** in the preceding auth phase.
- Camera lifecycle regression after checking isolation across two cameras:
  **2 passed**.
- `npm.cmd run build` in `frontend`: **passed** (`tsc --noEmit` and Vite build).
- Browser: real resource values and navigation verified. Overview overflow checks
  passed at 390, 768 and 1440 px; administration, playback and health navigation
  checked at 390 px. CPU/RAM trends are based only on received samples.
- PostgreSQL smoke check against the existing `Intelligent-VMS` database:
  login, role/permission response, logout revocation, login after app restart,
  user management, and no password-hash exposure **passed**.
- `Intelligent-VMS` is the existing PostgreSQL database shown in pgAdmin and is
  the active local database. The sample `.env.example` matches this name.
- Company-provided AVI in the local store: packet timestamp probe succeeded,
  recording completed as **ready** with one segment, and ranged playback returned
  HTTP **206**. Source footage stayed on local storage.
- Browser workflow with multiple real company videos: **not run in this pass**.
- AI detector/tracker test suite: **not run in this pass**.
- PostgreSQL connection: **verified** against the pre-existing database.
  Docker deployment remains unverified.

## Known limits and pending work

- Virtual feeds play processed recording segments in the browser. They are not
  server-published RTSP streams, and `running` reflects requested playback state,
  not a measured connection health signal.
- Physical RTSP/ONVIF ingestion, secure physical-camera credentials, reconnects,
  and hardware validation are pending camera access and a streaming design.
- The detector exists separately; per-camera AI toggles and detection overlays
  are not integrated into the dashboard.
- Multi-object analytics, recording retention/orphan cleanup, and PostgreSQL
  schema migration/versioning tooling remain pending.
- No practical simultaneous-camera CPU/GPU/RAM limit has been measured yet.
- RTSP camera registration and authenticated MJPEG preview have been implemented;
  actual RTSP transport and physical CCTV hardware validation remain pending.
  Each viewer decodes separately; continuous recording and ONVIF are not included.

## Architecture notes

- SQLAlchemy Core tables keep recordings, segments and cameras in one configured
  database. A camera references a ready recording and its segments.
- The current monitor consumes the existing authenticated segment playback API;
  this avoids duplicating upload, validation and transcoding logic.
- Video files remain in local storage. Camera deletion only removes its database
  registration.

## Hardware-dependent verification

- Physical CCTV validation is pending; none is claimed.
- Company-provided sample footage was not present in the repository and was not
  uploaded elsewhere. Existing synthetic-media tests cover segmentation only.
