# Candidate Customer Installation & Operations — 0.1.0-rc3

Authoritative production deployment uses `compose.production.yml` via PowerShell lifecycle scripts (`scripts/setup.ps1`, `scripts/start.ps1`, `scripts/status.ps1`, `scripts/stop.ps1`). Do **not** deploy `docker-compose.yml` or `docker-compose.recordings.yml` for production.

## Quick Staging / Production Setup

1. Install Docker Desktop (Windows, Linux containers enabled) or Docker Engine on a qualified server. Prepare PostgreSQL (external DB by default, or pass `-BundledDb`) and trusted TLS certificates `fullchain.pem` and `privkey.pem`.
2. Initialize configuration:
   ```powershell
   ./scripts/setup.ps1 -TlsDirectory 'C:\VMS-Certificates'
   # Or with single-node bundled PostgreSQL:
   ./scripts/setup.ps1 -TlsDirectory 'C:\VMS-Certificates' -BundledDb
   ```
3. Build and start services:
   ```powershell
   ./scripts/start.ps1 -Build -Profile medium
   # For high-scale (60+ camera target) with sharded recorders, GPU AI, and BSD-3 Valkey:
   ./scripts/start.ps1 -Build -Profile enterprise -DistributedRecorders -AiGpu -Valkey
   ```
4. Verify running version & health:
   ```powershell
   ./scripts/status.ps1
   curl.exe -sk https://localhost:8443/api/version
   curl.exe -sk https://localhost:8443/api/health
   ```

## Operator Workflows

- **Cameras (`Live view`):** Add authorized literal-IP RTSP cameras (`VMS_CAMERA_NETWORKS`), inspect live HLS/WebRTC feeds (using low-bandwidth substreams in grid tiles and main stream fullscreen), toggle per-camera AI where worker is online, and monitor separate live/recording status indicators.
- **Recordings & Legal Hold (`Playback library`):** Filter by camera or status, stream historical 30-minute (`1800s`) MP4 segments with speed controls and auto-next, and use **Protect / Unprotect** (`recording.manage` permission) to lock critical recordings against automatic retention pruning.
- **Retention:** `storage-retention` runs automatically on `RETENTION_CYCLE_SECONDS` (default 3600s), warns and logs `storage_low_disk_warning` / `storage_retention_cleanup` to `audit_logs`, never deletes `active` or `protected` footage, and never removes unindexed files without DB records. Use `--dry-run --once` to preview deletions safely.
- **Backup & Restore:** Use [`./scripts/backup_restore.ps1`](../../scripts/backup_restore.ps1) and [`BACKUP_RESTORE.md`](../BACKUP_RESTORE.md) before schema upgrades.
