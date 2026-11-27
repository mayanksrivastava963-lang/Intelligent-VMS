# Test Report — Intelligent-VMS 0.1.0-rc3 (2026-11-27)

## Follow-up Validation (Later on 2026-11-27)

- Full backend and AI test suite: **127 passed in 103.46 s** after adding offline admin recovery, validation-secret rewrite, and migration revision-length coverage.
- Live validation database: rotated PostgreSQL credential connected successfully; four stored RTSP camera sources decrypted with the rotated session secret after a WSL/database restart.
- RC3 Docker build: **not passed**. The guarded attempt was interrupted when host RAM reached 92.4% used. API and browser checks were not rerun; only PostgreSQL is currently running.

## Observed Test Results (`0.1.0-rc3` Source Tree)

| Check | Command | Observed Result |
| --- | --- | --- |
| Full Backend + AI Pytest Suite | `services\ai_engine\.venv\Scripts\python.exe -m pytest backend/tests services/ai_engine/tests -p no:cacheprovider -q` | **124 passed in 67.56s** (0 failed, 0 skipped; SQLite/mocked unit fixtures for isolation) |
| Frontend TypeScript + Vite Build | `npm --prefix frontend run build` | **Exit 0 in 338ms** (`index.js` `288.33 kB`, `hls.light` chunk `361.95 kB` / `115.24 kB` gzip; 0 bundle warnings) |
| Docker Compose Config Validation | `docker compose --env-file ... config --quiet` | **6 / 6 configurations exit 0** (`production`, `validation`, `bundled-db`, `ai-gpu`, `valkey`, `distributed-recorders`) |
| Validation Script CLI Checks | `rotation_test.py --help`, `progressive_load_test.py --dry-run` | **Exit 0**; progressive harness accurately detected laptop RAM pressure and blocked synthetic spawning |
| Live Validation API (`127.0.0.1:8443`) | `curl -sk https://127.0.0.1:8443/api/health` & `/api/version` | `/api/health` `200 {"status":"ok"}`; `/api/version` `404` (confirms live stack runs preserved RC1 image) |

## New Regressions Covered in `0.1.0-rc3`

- `backend/tests/test_retention.py`: `--dry-run`, `protected` legal-hold footage surviving expiry and extreme low-disk pressure, `active` marker skip, DB `audit_logs` retention cleanup record, unlink-error metadata preservation, `RETENTION_CYCLE_SECONDS` minimum validation, and `PUT /api/videos/{id}/protection` RBAC + audit tests.
- `backend/tests/test_multi_recorder.py`: deterministic camera shard balancing across workers, `recorder_workers` heartbeat & stale-owner failover checks, distributed per-camera advisory lease duplicate prevention, immediate recorder stop on dropped DB lease, `/api/system/metrics` + `/api/version` schema, and live Redis `vms:ai:worker:heartbeat` AI availability + 503 pressure blocking checks.

## Unexecuted Server / Hardware Tests (Still Pending)

- Full 60-camera progressive streaming & soak runs (`4 -> 8 -> 16 -> 32 -> 48 -> 60+`, 2h/8h/24h/72h)
- Live 30-minute (`1800s`) RTSP rotation test (`scripts/rotation_test.py --segment-seconds 1800`)
- Physical CCTV camera / ONVIF / H.265 / browser WebRTC interoperability & failure recovery drills
- Clean-server deployment build (`scripts/start.ps1 -Build`) and container CVE scan
