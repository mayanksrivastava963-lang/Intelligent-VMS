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
- Fixed single-segment looping: a finished virtual clip now remounts its player
  for the next cycle instead of staying paused.
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
- One RTSP decoder per camera per API process; dashboard viewers share a bounded
  latest-frame buffer. Camera API now reports connection status from decoder
  activity and frame freshness. Stop/restart/remove isolate each acquisition.
- Live view filters by source and location. RTSP badges show connecting, online,
  reconnecting or offline; virtual badges follow browser playback events.
- Per-camera AI switches persist in a separate database table. Authenticated
  dashboard frames are sampled at a configurable interval and processed by one
  shared SSDLite model with a bounded inference slot. Fresh bounding boxes,
  confidence labels and counts appear on camera tiles. AI errors do not stop
  playback.

## Validation run

- `python -m pytest backend/tests services/ai_engine/tests -q` using the
  existing Python 3.12 AI environment: **66 passed**.
- Backend camera/recording tests: **24 passed**, including a synthetic MP4 plus
  AVI upload, two independent virtual cameras and ranged segment playback;
  shared RTSP decoder and offline status were checked with a mocked source.
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
- Synthetic MP4 and AVI were processed into separate, independently controlled
  virtual cameras in an API integration test. Browser rendering of both feeds
  together was also tested at http://127.0.0.1:5173 with a separate temporary
  SQLite database. Both files uploaded and processed to ready, both browser
  players ran together and looped beyond their five-second duration, stopping
  one left the other playing, and 2-column layout rendered at 1440 px.
  The temporary smoke environment did not touch the existing PostgreSQL DB.
- Direct detector smoke test with a synthetic 320x180 JPEG: model initialized
  and returned a valid response with zero detections in 7.32 seconds, including
  cold model startup. This does not measure accuracy on CCTV footage.
- Browser AI smoke test against the temporary local setup: enabled AI on a
  running virtual camera, observed repeated HTTP 200 frame-analysis responses,
  then disabled AI while the video remained playable. The synthetic footage
  had no recognized objects, so bounding-box placement with real detections
  remains unverified in browser.
- AI detector/tracker tests were included in the **66 passed** full suite.
- PostgreSQL connection was verified against the pre-existing database in an
  earlier phase. This pass used a separate temporary SQLite database for
  browser smoke testing. Docker deployment remains unverified.

## Known limits and pending work

- Virtual feeds play processed recording segments in the browser. They are not
  server-published RTSP streams. Their `running` state is a requested state;
  each browser tile separately reflects loading, playing and paused events.
- Physical RTSP transport and ONVIF hardware validation are pending camera
  access. No physical camera has been tested.
- Dashboard AI inference samples frames only while a viewer has the page open.
  Background AI analytics and production-grade frame synchronization are not
  implemented. Late results are discarded, and bounding boxes appear briefly
  for recent samples only.
- Multi-object analytics, recording retention/orphan cleanup, and PostgreSQL
  schema migration/versioning tooling remain pending.
- No practical simultaneous-camera CPU/GPU/RAM limit has been measured yet.
- RTSP camera registration and authenticated MJPEG preview have been implemented.
  One decoder is shared among viewers within a single API process. Continuous
  recording, MediaMTX distribution, and ONVIF are not included.
- Docker Desktop engine was unavailable during this validation, so simulated
  MediaMTX/RTSP transport and container deployment were not tested.
- The recording API Docker image does not include the heavy AI dependencies;
  local AI inference needs the existing Python 3.12 AI virtual environment.
- `PROJECT_REQUIREMENTS.md` is absent from the repository; the attached final
  development prompt was used for this phase.

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
