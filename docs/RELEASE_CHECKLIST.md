# Release Gate Checklist — Intelligent-VMS 0.1.0-rc3

**Status: NOT APPROVED for commercial rollout (Engineering candidate with server/hardware/legal gates open).**

## Engineering & Automated Verification Completed

- [x] Production upload and virtual-camera creation UI removed (`App.tsx`).
- [x] Production ingestion/simulation APIs and Swagger docs disabled by default (`main.py`).
- [x] Existing footage preserved; unindexed files protected from auto-deletion (`retention.py`).
- [x] Legal-hold `protected` flag (`0006` migration, API `PUT /api/videos/{id}/protection`, UI toggle, retention skip) implemented and unit-tested (`test_retention.py`).
- [x] Scheduled `storage-retention` wired into `compose.production.yml` with healthy 30s heartbeat refresh and DB audit logging.
- [x] Optional AI worker (`--profile ai`) and GPU overlay (`compose.ai-gpu.yml`) wired with live Redis availability reporting and VRAM cap.
- [x] Per-camera PostgreSQL advisory lease & distributed sharding (`VMS_RECORDER_MODE=distributed`, `compose.distributed-recorders.yml`) implemented and unit-tested (`test_multi_recorder.py`).
- [x] Preventive `75/80/85` ResourceGuard thresholds with hysteresis, AI shedding, and existing-recording preservation tested (`test_resource_guard.py`).
- [x] Bundled PostgreSQL option (`compose.bundled-db.yml`) + external PG enterprise support + BSD-3 Valkey overlay (`compose.valkey.yml`) validated via `docker compose config --quiet`.
- [x] Frontend HLS bundle optimized via `hls.light.mjs` (< 365 KB chunk, zero build warnings) and `production.conf.template` upload proxy block removed.
- [x] Repeatable production validation scripts prepared (`scripts/rotation_test.py`, `scripts/progressive_load_test.py`, `scripts/backup_restore.ps1`).
- [x] Offline administrator diagnosis/recovery CLI added and tested; validation secret rotation re-encrypts saved camera sources and revokes sessions.
- [x] Compose empty camera-limit default and overlong Alembic revision ID corrected; targeted and full automated suite pass (127 tests).
- [x] Local validation Docker stack built and started with the supported RC3 workflow; `/api/version`, migrations, API/browser administrator login, playback, protection toggle, and idle worker health verified on 2026-11-27.

## Remaining Open Release Gates (Required on Production Server / Before Shipping)

- [ ] Rebuild and deploy `0.1.0-rc3` Docker images on dedicated staging/production server (`scripts/start.ps1 -Build`) and verify `/api/version` returns `0.1.0-rc3`.
- [x] Recover the local validation administrator password and verify login through the running API and browser. The stored account hash now matches the requested validation password; bootstrap environment secrets are intentionally separate.
- [ ] Execute actual 1800-second (`30 min`) rotation test (`scripts/rotation_test.py`) with live RTSP streams and confirm gapless Range playback.
- [ ] Execute progressive load tests (`scripts/progressive_load_test.py --tiers 4,8,16,32,48,60`) and 2h/8h/24h/72h soaks on production hardware.
- [ ] Validate multi-worker distributed failover (`compose.distributed-recorders.yml`) against live PostgreSQL + MediaMTX streams.
- [ ] Validate physical CCTV camera models, ONVIF/H.265/browser compatibility matrix, and browser HLS/WebRTC playback under load.
- [ ] Complete isolated backup/restore & DB/network/storage fault-injection drills (`scripts/backup_restore.ps1`) and clean-environment installation test.
- [ ] Run container image vulnerability scans (e.g. Trivy/Grype) on freshly built `0.1.0-rc3` images.
- [ ] Complete commercial licensing sign-off (choose Valkey vs Redis, confirm FFmpeg GPL source compliance & codec patents, approve AI weight terms, confirm Docker Desktop/Engine licensing).

## Production-Server Validation Procedure (Not Yet Executed)

Use a dedicated staging server with production-class hardware and an isolated validation database/recording volume. Record image digest, `/api/version`, `docker ps`, `docker stats --no-stream`, host RAM/CPU, disk free space, and GPU VRAM before and after every run. Keep the 85% admission guard enabled; stop escalation when any tier is blocked.

1. **Real 1800-second rotation:** Configure `RECORDING_SEGMENT_SECONDS=1800` and a continuous RTSP source. Run `python scripts/rotation_test.py --env-file storage/deployment-validation/validation.env --prompt-password --segment-seconds 1800 --report rotation-report.json`. Require two completed consecutive segments, playable byte ranges, timestamps with no gap above the configured 15-second tolerance, and continuous recorder health. A 60-second quick check is not certification.
2. **Physical CCTV matrix:** For each vendor/model/firmware, record ONVIF discovery, RTSP main/substream URL, H.264/H.265, audio mode, authentication, time sync, reconnect after camera/network loss, and browser HLS/WebRTC behavior. Verify independent recording and two complete playback segments per configuration. Save sanitized evidence without RTSP credentials.
3. **60-camera workload:** On server hardware, run `python scripts/progressive_load_test.py --tiers 4,8,16,32,48,60 --duration 120 --prompt-password` in the isolated validation topology. Require every camera online and recording, zero harness failures, p95 API latency below the configured limit, and resource policy below block. Follow with `--tiers 60 --soak integration|operational|day|stability --prompt-password` for separate 2h/8h/24h/72h runs. Record dropped frames, recording gaps, playback success, disk growth, CPU/RAM/VRAM and network usage; do not infer capacity from synthetic 320x180 streams alone.
4. **Distributed recorder failover:** Start the staging stack with `-DistributedRecorders`; verify distinct worker heartbeats and per-camera advisory leases. With continuous streams, stop one recorder worker, measure stale-worker takeover within the configured `RECORDER_TAKEOVER_SECONDS`, confirm no duplicate recording owner or lost segments, then restart it and verify clean lease handoff. Repeat with PostgreSQL/network interruption and retain fault timestamps.
5. **Backup and restore:** Run `./scripts/backup_restore.ps1 -Action backup -Validation`, verify its manifest/checksums and recording-file inventory, then restore only into an isolated clone using `-Action restore -BackupPath <backup-directory> -Validation`. Compare user/camera/recording counts, protected flags, camera-source decryptability, playback, and application health. Never drill by overwriting the live production database.
6. **Security and licensing:** Scan the exact freshly built API, web, AI (if shipped), PostgreSQL, MediaMTX and cache image digests with Trivy or Grype; record scanner version, database date, findings and dispositions. Review TLS, RBAC, cookie policy, secret handling, camera network restrictions and backup access. Obtain written commercial sign-off for the items in [COMMERCIAL_LICENSING.md](./COMMERCIAL_LICENSING.md) before customer rollout.
