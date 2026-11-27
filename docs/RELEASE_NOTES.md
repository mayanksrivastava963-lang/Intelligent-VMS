# Intelligent-VMS 0.1.0-rc3 Release Notes (2026-11-27)

Internal engineering release candidate. **Not approved for commercial deployment without server-tier load verification, 30-minute physical rotation evidence, and legal sign-off.**

## Key Capabilities & Improvements in `0.1.0-rc3`

1. **Build Identification:** Added `/api/version` endpoint and Dockerfile/script build args (`VMS_BUILD_VERSION`, `VMS_BUILD_SHA`, `VMS_BUILD_TIMESTAMP`) to verify deployed container versions unambiguously.
2. **Production Retention & Legal Hold:** Enabled `storage-retention` automatically in `compose.production.yml` with continuous heartbeat keepalive, Alembic `0006` `protected` column, `PUT /api/videos/{id}/protection` API + UI toggle, `--dry-run`, `audit_logs` records, and unlink-first metadata consistency.
3. **Production AI Worker Options:** Added optional `--profile ai` service (`cpu` default Dockerfile arg, `compose.ai-gpu.yml` for CUDA + NVIDIA GPU reservation + `AI_GPU_MEMORY_FRACTION`), live Redis availability reporting (`vms:ai:worker:heartbeat`), and container healthcheck.
4. **Distributed Recorder Sharding:** Added `VMS_RECORDER_MODE=distributed` (`compose.distributed-recorders.yml`), per-camera PostgreSQL advisory locks, `recorder_workers` heartbeat tracking, and configurable failover takeover alongside `single` global-lock compatibility.
5. **Licensing & DB Deployment Flexibility:** Added `-BundledDb` (`compose.bundled-db.yml`) option for single-node installs alongside external PostgreSQL enterprise deployments, plus `-Valkey` (`compose.valkey.yml`, BSD-3-Clause) drop-in Redis replacement.
6. **Frontend & Security Hardening:** Optimized HLS client via `hls.light.mjs` (~362 KB async chunk), removed legacy unbuffered upload proxy rules in Nginx, and added `-rtsp_flags filter_src` packet source filtering.
7. **Server Validation Tooling:** Added authenticated `scripts/rotation_test.py`, `scripts/progressive_load_test.py`, `scripts/backup_restore.ps1`, `docs/BACKUP_RESTORE.md`, and `docs/HARDWARE_SIZING_GUIDE.md`.
