# Deployment Evidence — Intelligent-VMS 0.1.0-rc3 (2026-11-27)

**Internal engineering candidate; customer deployment remains blocked pending server-scale load verification and commercial licensing sign-off.**

## Verified Container Runtime State (Pre-rc3 Stack Preserved)

Because the development laptop operates at ~89–96% RAM (`15.82 GiB` total) and `scripts/start.ps1` intentionally enforces an 85% build/startup safety guard, the running validation containers remain preserved on the earlier RC1 build (`intelligent-vms-api:0.1.0`, digest `sha256:116207296979`, built `2026-11-27 10:53 +0530`):

- Verified live probe on `https://127.0.0.1:8443/api/health`: `HTTP 200 {"status":"ok"}`.
- Verified live probe on `https://127.0.0.1:8443/api/version`: `HTTP 404` (confirms running image precedes `0.1.0-rc3`).
- Preserved runtime evidence: HTTPS frontend + SPA routes, Argon2id login + Secure cookies, unauthenticated API/playback/live stream denial (`401`/`403`), Range playback (`206`) across four retained synthetic recordings, container recreation persistence, external Windows PostgreSQL read-only `SELECT 1`, duplicate-recorder rejection, and Docker GPU enumeration (`RTX 3050 Laptop, 4096 MiB`).
- Historical 4-stream synthetic benchmark (`320x180`, 5 fps, `256 kbps`) stopped cleanly at 49.4s after laptop RAM hit `90.6%` (`3/4` recording online, 4 segments indexed & range-readable). Not a sustained capacity claim.

## Verified `0.1.0-rc3` Source & Configuration Checks

- Automated Python test suite (`backend/tests`, `services/ai_engine/tests`): updated to include retention protection/dry-run/audit/recovery tests (`test_retention.py`) and distributed per-camera advisory lease/failover & AI Redis heartbeat tests (`test_multi_recorder.py`) alongside all baseline tests (latest count recorded in `TEST_REPORT.md`).
- Frontend production build (`tsc --noEmit && vite build`): exit `0` in ~338 ms, zero bundle-size warnings (`hls.light` async chunk = `361.95 kB` / `115.24 kB` gzip).
- Docker Compose configuration parsing (`docker compose config --quiet` exit `0`) across all six target deployment topologies (`production`, `validation`, `bundled-db`, `ai-gpu`, `valkey`, `distributed-recorders`).
- CLI validation checks passed (`scripts/rotation_test.py --help` exit `0`, `scripts/progressive_load_test.py --dry-run` exit `0`).

## Remaining Gates (Dedicated Production Server)

1. Rebuild and deploy `0.1.0-rc3` containers (`scripts/start.ps1 -Build`) and confirm `GET /api/version` returns `0.1.0-rc3`.
2. Execute `scripts/rotation_test.py --segment-seconds 1800` across two consecutive 30-minute live RTSP segments.
3. Execute `scripts/progressive_load_test.py --tiers 4,8,16,32,48,60` and 2h / 8h / 24h / 72h soaks on high-RAM/CPU production hardware.
4. Execute physical CCTV/ONVIF matrix, browser WebRTC/HLS decode checks, container CVE scan, backup/restore drill, and clean-machine installation test.
