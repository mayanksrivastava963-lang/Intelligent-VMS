# Intelligent-VMS RC3 portable internal candidate

NOT APPROVED FOR COMMERCIAL DISTRIBUTION. See THIRD_PARTY_NOTICES.md and docs/COMMERCIAL_LICENSING.md. Included license texts do not replace corresponding-source obligations, legal approval, vulnerability scans or release qualification.

## Prerequisites

Windows x64 with Docker Desktop running **Linux containers**, Docker Compose v2+ and Windows PowerShell 5.1+. No host Python, Node, PostgreSQL, FFmpeg or MediaMTX is needed. Docker itself is not included. Linux x86-64 can use Docker Engine/Compose and PowerShell 7 with these scripts; this platform is not yet validated. ARM/native Windows containers are not supported by these images. Offline operation after Docker is installed: all runtime images are in images.tar, and start forbids pulls and builds.

Development: 16 GB RAM laptop, adequate free memory below the 85% guard, approximately 15 GB free disk for archive/extraction/import plus recording storage. This is not a 60-camera hardware guarantee. Production target remains 60 cameras, with configurable CPU, RAM and concurrency limits; use docs/HARDWARE_SIZING_GUIDE.md for bitrate/storage/network planning and qualify on the actual server. AI is absent: the available GPU image has not passed inference validation.

## Install on a new machine

1. Extract the complete outer TAR into a new private local directory (avoid network shares). Use `tar -xf Intelligent-VMS-0.1.0-rc3-portable.tar` or an archive tool. Check its SHA-256 against the supplied adjacent .sha256 file using `Get-FileHash`.
2. Open PowerShell in the extracted directory. Run `./install.ps1 -SelfSigned` for localhost testing, or `./install.ps1 -TlsDirectory C:/secure/vms-tls` with trusted `fullchain.pem` and `privkey.pem` supplied by the recipient. No sender certificate/key is packaged. The self-signed option needs a browser exception and is for localhost only.
3. Enter your administrator username and a unique 12+ character password at the hidden prompt. Enter approved camera CIDRs and the certificate hostname. Fresh database, session/encryption and media secrets are generated locally. Restrict access to .env.production and TLS keys. Preserve the session secret in private backups: encrypted camera credentials depend on it.
4. Run `./start.ps1`. PostgreSQL initializes, Alembic migrations complete, then the application starts. Open https://localhost:8443/ and sign in with your chosen account. Existing databases never receive a bootstrap password reset.
5. Run `./status.ps1`; `./stop.ps1` stops services without deleting volumes. To load images separately, run `./import-images.ps1`. No rebuild is required. If PowerShell execution policy blocks scripts, review scripts and use a process-scoped policy allowed by your organization; do not weaken machine-wide policy.

Default access is loopback-only. For LAN deployment configure VMS_BIND_ADDRESS, VMS_PUBLIC_HOST, trusted TLS, camera networks and firewall deliberately. Port 8443/TCP and WebRTC 8189/UDP are configurable/exposed as described in Compose. PostgreSQL/Redis are not published to the host. Avoid overlapping control subnet 172.30.85.0/24. Volume names default to intelligent-vms-*; never reuse them for a second installation. Configure unique volume/project names first.

## Optional private data transfer (not in this package)

On a portable installation run `./backup.ps1 -Destination D:/private-vms-backup`. It stops all application writers, exports PostgreSQL in binary custom format and archives the recording volume. It also copies private environment settings for the encryption key. **This backup is confidential and unencrypted**: use encrypted removable storage and restrict access. It is never added to the default distribution. Source services stay stopped until `./start.ps1` is run. Allow sufficient backup disk space and a maintenance window.

On the destination run install first, but do not start. Then run `./restore.ps1 -Source D:/private-vms-backup`. Only an empty database/recording store is accepted. The original encryption key is restored while destination database credentials, network and TLS settings are retained. Existing account passwords survive. Review camera addresses and availability before starting. A partial restore failure needs investigation; never wipe existing volumes automatically. Redis cache and old TLS private keys are intentionally not transferred.

## Verification and limitations

Read VALIDATION.md for executed evidence and unexecuted gates. Verify `/api/version`, `/api/health`, container health, administrator login and playback after install. Source/image parity was checked for shipped backend/recorder runtime and frontend assets; image IDs are in images.json. The application images originally used legacy `0.1.0` tags; package-specific RC3 aliases refer to the exact inspected images, not rebuilt or relabeled older code.

Production gates remain: real 1800-second recording rotation; physical CCTV/codec compatibility; 60-camera throughput; distributed failover; 2/8/24/72-hour soak; isolated restore drill; security scanning; commercial licensing and source-distribution clearance. Never treat an unexecuted check as passed. Keep the 85% resource safety guard enabled.

## Existing local validation installation backup

After importing package images, the separate backup script can also read an existing source environment:

```powershell
./backup.ps1 -Destination D:/private-vms-backup -SourceEnvironment C:/Projects/Intelligent-VMS/storage/deployment-validation/validation.env
```

This is an explicit maintenance operation: it stops the source application writers and exports PostgreSQL plus recordings. It has NOT been executed against personal data during packaging. Resume that source with its original project start script. The destination restore is restricted to a newly configured, empty installation. Never include this private backup in the public/default archive.

License reference pages: https://www.postgresql.org/about/licence/ and https://redis.io/legal/licenses/ . Actual Redis 7.4.12 license text was extracted from its official download.redis.io release archive; this does not grant commercial clearance. API license archive contains Debian copyright/common-license texts and installed Python distribution metadata; nginx and MediaMTX licenses were copied from running images. Frontend dependency lockfile and available runtime license notices are included. Complete transitive compliance and corresponding-source delivery are pending.
