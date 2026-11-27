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

# Product maturity audit — 2026-11-26

Status: **engineering hardening candidate; customer release blocked**.
This is a targeted source/configuration audit, not an exhaustive review of every
button, endpoint, dependency or failure mode. Existing uncommitted work was preserved.

| Priority | Finding | Disposition / evidence |
| --- | --- | --- |
| Critical | Retention deleted unindexed files after 24 hours; DB outage footage could be lost. | Removed orphan deletion, regression proves preservation. Retention service now requires explicit profile. No existing data was deleted. |
| High | Runtime configuration uses operator_password but API bootstrap read password. | Fixed; production-factory test logs in using the actual config key. Legacy tests had masked it. |
| High | Upload/simulation APIs and production navigation exposed development workflows. | Default route table excludes upload, retry, virtual creation and JPEG inference upload. Legacy camera controls denied; files and playback retained. UI picker, drag/drop, creation and simulation player removed. Internal app-factory opt-in remains for tests. |
| High | Any administrator-supplied RTSP host could be reached by workers. | Main/substream literal addresses checked against explicit CIDRs at onboarding, start/restart and startup. Empty allowlist denies. DNS names deliberately unsupported pending pinned resolution. Egress firewall and redirect handling still require validation; this is not a complete SSRF assessment. |
| High | Recorder that never emitted its first frame escaped stale watchdog. | Deadline now covers initial connection and later stalls; regression tests cover both. |
| High | Requested running state shown as actual live status. | Labels corrected; separate recorder progress status exposed; stale online progress downgraded after 30 seconds. Progress is not proof of durable segment integrity. |
| High | Production MediaMTX accepted synthetic publishers. | Moved publisher paths into explicit benchmark configuration. Internal anonymous reading remains a release security concern. |
| High | No validated installer/deployment, physical camera tests or recording soak. | Open. Docker command unavailable. Do not ship a customer release. |
| High | Recorder ownership, maximum admitted load and resource shedding absent. | Open. One recorder only; no HA or multi-node capacity claim. |
| High | Retention metadata/file deletion not transactional; no evidence hold. | Open. Retention opt-in only; needs protected-recording policy and failure-injection tests. |
| High | Runtime create_all/ad-hoc ALTER coexists with migrations. | Open. PostgreSQL migration/upgrade/rollback test required; never reset the company DB. |
| High | Worker health checks only SELECT 1; do not prove worker or recording health. | Open. Camera progress status helps but is not a substitute for service heartbeats/continuity alerts. |
| High | Unpinned container tags, broad AI development dependency list and unresolved redistribution rights. | Open. Dependency/license review required before customer packaging. |
| Medium | First-time wizard, ONVIF, camera editing/testing, schedules, GIS, saved layouts and secure audited exports incomplete/absent. | Open. Do not advertise these capabilities. |
| Medium | Bootstrap can create an admin when configured username changes. | Open. A formal one-time setup lifecycle and recovery policy are needed. |
| Medium | Legacy upload code remains in management source though routes are removed. | Internal factory only; further source-package separation is pending. |
| Medium | Existing 60-camera harness assumes hostname sources and lacks sustained resource cutoffs. | Open; do not use it against a customer deployment. Adapt to an isolated approved IP network before running. |
| Low | HLS frontend chunk exceeds 500 kB. | Build warning; dynamically loaded. Measure browser behavior before further splitting. |

Inspected areas include API/auth, configuration, database/session/models/migrations,
camera/media services, recording publication/retention, AI detector/worker imports,
frontend main workflow/login/command palette, Docker/Nginx/MediaMTX, tests and
benchmark/startup scripts. Full audit of all remaining files is outstanding.
