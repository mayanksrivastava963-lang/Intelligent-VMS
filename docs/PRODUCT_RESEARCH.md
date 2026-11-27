# Current update — 2026-11-27

**Internal release candidate; customer rollout remains blocked.** Actual Docker
builds/startup, HTTPS/authentication, saved recording range playback, external
PostgreSQL read-only access and duplicate-recorder rejection are verified.
The four-camera run hit the 90% RAM cutoff. No sustained capacity or 30-minute
rotation pass is claimed. Updated Python/frontend dependency audits report zero
advisories after Cryptography/Pillow upgrades; complete security and licensing
clearance remain open.

See [current measured evidence](DEPLOYMENT_EVIDENCE.md) and
[current installation instructions](DOCKER_DEPLOYMENT.md).
Use scripts/setup.ps1 then scripts/start.ps1 -Build for customer staging;
use scripts/start.ps1 -Validation for the existing isolated developer stack.
These replace the earlier Docker-unavailable, no-package and old Compose startup
instructions below. Recovery paths still require fault-injection validation.

---

## Earlier milestone record (historical; not current installation instructions)

# Product research — 2026-11-26

This is an initial evidence-based architecture review, not a completed comparative
certification. Official pages below were retrieved during this pass. No vendor
source, branding, assets or UI designs were copied.

| Capability / official source | Observed approach and why it matters | Intelligent-VMS decision, gaps and implications |
| --- | --- | --- |
| [Milestone system architecture](https://doc.milestonesys.com/xprotect/system-architecture-guide-for-it-professionals/v/en/overall-system-architecture) | Components can share one capable server or span servers; failover recorders are optional. | Keep management, recording, media and optional AI as logical workers. Existing processes support one server; node ownership/failover is missing. Multiple recorder replicas are unsafe until leases are implemented. Avoid unnecessary orchestration. |
| [Nx Witness FAQ](https://www.networkoptix.com/nx-witness/faq) | Server/camera expansion, recording schedules, permissions, customizable layouts and network planning are explicit deployment concerns. | Existing paged grids, roles and substreams are useful. Saved layouts, schedules and measured sizing remain absent. Vendor hardware claims do not transfer to our software. Nx commercial licenses are not included or required for this independent implementation. |
| [AXIS feature guide](https://help.axis.com/en-us/axis-camera-station-pro-feature-guide) | Server handles camera communication, clients consume live/recorded video. Stream quality options, installation verifier and system health tooling matter; grid capacity depends on hardware. | Use shared MediaMTX pulls and main/substream viewing; retain independent recorder. Add honest recording status. Installation verification, physical compatibility matrix and browser codec validation remain release gates. Axis integration or certification is not claimed. |
| [Genetec Omnicast](https://www.genetec.com/products/unified-security/omnicast) | Retrieval returned a JavaScript-only shell. | Archiver, redundancy, permissions and sizing research is still pending; no detailed claims derived from this inaccessible page. |
| [ONVIF profiles](https://www.onvif.org/profiles/) | Profiles describe interoperable feature groups; conformance is separate from merely consuming network video. | Discovery, Profile T/G/M behavior, legacy Profile S guidance and formal conformance remain unimplemented/unverified. Do not label RTSP support as ONVIF certification. Discovery must be restricted to approved networks. |
| [MediaMTX authentication](https://mediamtx.org/docs/usage/authentication) | Internal credentials, HTTP authorization and JWT options; permissions include read, publish, playback, API and metrics. | Current Nginx session check protects public media HTTP paths. Control API has credentials. Internal anonymous reads are still a trust-boundary limitation; production benchmark publishing has been removed. Need end-to-end media authorization/revocation tests and isolated networks. |
| [FFmpeg formats](https://ffmpeg.org/ffmpeg-formats.html) | Segment muxer is relevant to copy-based recording. | Preserve 1800-second target and fragmented MP4 recovery strategy. Exact boundaries depend on source keyframes; measure durations and recovery, do not assume 1800 precisely. Codec/build licensing must be reviewed for the actual redistributed binaries. |
| [PostgreSQL backup](https://www.postgresql.org/docs/current/backup.html) | Official backup documentation is the basis for backup/recovery procedures. | Use migrations and backup both metadata and footage. An untested dump is not proof of recovery. Restore drill on isolated infrastructure is outstanding. |
| [FastAPI deployment concepts](https://fastapi.tiangolo.com/deployment/concepts/) | HTTPS, startup, restart, worker replication and memory need deliberate deployment choices. | Multiple API workers must not spawn per-viewer decoders. Production media is shared; local MJPEG remains single-process only. Shared rate limiter is needed across API workers. |
| [Docker Compose production](https://docs.docker.com/compose/how-tos/production/) | Built application images, restart policies and production-specific configuration are recommended. | Nginx image now builds the frontend, removing the host dist dependency. Docker CLI/engine unavailable here; image build, TLS, volumes and restart behavior remain untested. Pin verified image digests before release. |

Performance principles: stream-copy where compatible, use substreams for walls,
bound AI sampling, measure disk/network before promising capacity. Security
principles: deny unknown camera networks, protect media independently of UI,
preserve unindexed footage, and keep credentials out of responses.

Licensing: vendor documentation is reference material, not permission to copy
software. Review MediaMTX license, every dependency notice, model weight terms,
FFmpeg build flags, codecs and container distribution before any customer bundle.
See [third-party review](../THIRD_PARTY_NOTICES.md).
