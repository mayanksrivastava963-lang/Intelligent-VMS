# Resource-aware scalable configuration — rc2 source

Read [scaling boundaries and node partitioning](RESOURCE_AND_SCALING.md). Recorder,
API, media and AI allocations are configurable. Current horizontal boundary is
independent camera partitions, with separate database/storage/operator endpoints.
Unified federation, camera placement and recorder HA are not yet implemented.
Source changes have not been redeployed under the current high host memory load.

# Previous deployment update — 2026-11-27

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

# Current architecture

Browser -> Nginx TLS -> management API -> PostgreSQL metadata.
Browser -> Nginx authorization subrequest -> MediaMTX HLS/WebRTC.
Camera main/substream -> shared MediaMTX paths -> recorder / viewers / AI worker.
Recorder -> fragmented MP4 files + completed-segment metadata.
Optional AI worker -> bounded samples/inference -> Redis results + database alerts.

Recording is a separate process, independent of browser and AI. Target segment
duration is 1800 seconds, with keyframe-dependent boundaries. Current deployment
has one recorder and one recording volume. There are no ownership leases,
distributed failover, recording schedules or proven enterprise limits.

Management stores encrypted sources; API omits URLs. Explicit camera CIDRs and
literal IPs are required. Set VMS_CAMERA_NETWORKS before onboarding. Existing
out-of-policy running cameras are stopped on API startup, without deleting data.
This intentional upgrade behavior requires administrator review of the allowlist.

Internal upload routes require create_app settings internal_test_tools=True;
the standard entry point always disables them. Production UI contains no upload
or virtual-camera creation workflow. Historical recordings remain accessible to
authorized users. Conversion worker and benchmark publisher use explicit test
profiles/configurations; automatic retention requires the retention profile.

Next architecture gates: recorder ownership, heartbeats/continuity alerts,
bounded admission, protected footage retention, migration-only startup, independent
stream authentication, and isolated backup/recovery validation.
