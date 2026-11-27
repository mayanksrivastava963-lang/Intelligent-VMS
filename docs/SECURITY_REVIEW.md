# Security Review — Intelligent-VMS 0.1.0-rc3 (2026-11-27)

**Status: Engineering hardening implemented; full penetration testing, container CVE scan, and clean-install audit remain release gates.**

## Controls Implemented & Verified

- **Strict Camera Source Allowlist (SSRF Mitigation):** `allowed_camera_url` denies empty CIDRs, DNS hostnames (prevents DNS rebinding), loopback, link-local, multicast, unspecified, and IPv4-mapped IPv6 addresses. Rejected URLs containing credentials are omitted from API errors (`400` / `422`).
- **RTSP Packet Origin Filtering:** Both FFmpeg recorder (`services/recording_engine/rtsp_recorder.py`) and PyAV AI sampler (`services/ai_engine/worker.py`) pass `-rtsp_flags filter_src` to reject RTP packets from non-negotiated peer IPs. *Note: MediaMTX still requires firewall-level outbound egress restriction on `egress` network (`iptables`/VLAN isolation) so compromised cameras cannot return cross-subnet RTSP 302 redirects.*
- **Encrypted Source Credentials:** Camera URLs and substreams are Fernet-encrypted (`cryptography`, SHA-256 derived key from `VMS_SESSION_SECRET`) and never returned in API responses or logs.
- **Session, RBAC & CSRF Hardening:** Argon2id password hashes (`argon2-cffi`), HttpOnly/Secure/SameSite=Strict signed session cookies backed by revocable `user_sessions` DB rows, `X-VMS-Request: 1` write-header protection, Redis-backed (or Valkey) shared `LoginLimiter`, and RBAC permission enforcement across every route including `PUT /api/videos/{id}/protection`.
- **Authenticated Stream Access:** Nginx `/live/` and `/live-webrtc/` subrequests validate session cookies, `camera.read` permission, running status, and admission guard via `/api/stream-access`. Direct MediaMTX API (`9997`) and Redis (`6379`) ports are isolated on internal Docker network `control`.
- **Nginx Upload Proxy Removal:** Obsolete unbuffered `/api/videos` 3600s upload proxy block removed from `infrastructure/nginx/production.conf.template`; global `client_max_body_size 1m` applies.
- **Non-Root Container Privileges:** Containers drop root (`recorder` uid 10001, `aiworker` uid 10002) and set `no-new-privileges:true` with bounded memory/CPU/PIDs/log rotation.
- **Audit Trail:** Login success/failure, logout, user/password changes, alert acknowledgements, recording legal-hold protection (`recording_protected`/`recording_unprotected`), low-disk warnings (`storage_low_disk_warning`), and automatic retention deletions (`storage_retention_cleanup`) are persisted to `audit_logs`.

## Open Security Release Gates

- [ ] Network firewall / VLAN egress restriction verification against RTSP HTTP/302 redirect bypasses in live MediaMTX environment.
- [ ] Container & OS package vulnerability scan (Trivy / Grype) after rebuilding `0.1.0-rc3` images on production server.
- [ ] Scoped internal service credentials between MediaMTX & FFmpeg recorder (replace shared `vms-media` reader where needed).
- [ ] Unattended boot, secret backup/rotation, and DB backup/restore failover drills (`scripts/backup_restore.ps1`).
