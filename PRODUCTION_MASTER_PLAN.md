# Current scalability continuation — rc2

Completed in source: configurable preventive thresholds, bounded resource sampling,
AI shedding, camera admission serialization, recording-preservation tests, hardware
profiles and multi-server partition guidance. No permanent laptop capacity ceiling.
Pending deployment: current host pressure blocks safe rebuild/start. See
[resource validation](docs/RESOURCE_VALIDATION.md). Unified cross-node management,
recorder HA and production-server benchmarks remain required; do not substitute
partition examples for those capabilities.

# Previous deployment update — 2026-11-27

**Internal release candidate; customer rollout remains blocked.** Actual Docker
builds/startup, HTTPS/authentication, saved recording range playback, external
PostgreSQL read-only access and duplicate-recorder rejection are verified.
The four-camera run hit the 90% RAM cutoff. No sustained capacity or 30-minute
rotation pass is claimed. Updated Python/frontend dependency audits report zero
advisories after Cryptography/Pillow upgrades; complete security and licensing
clearance remain open.

See [current measured evidence](docs/DEPLOYMENT_EVIDENCE.md) and
[current installation instructions](docs/DOCKER_DEPLOYMENT.md).
Use scripts/setup.ps1 then scripts/start.ps1 -Build for customer staging;
use scripts/start.ps1 -Validation for the existing isolated developer stack.
These replace the earlier Docker-unavailable, no-package and old Compose startup
instructions below. Recovery paths still require fault-injection validation.

---

## Earlier milestone record (historical; not current installation instructions)

# Intelligent-VMS production master plan

This file was absent at the start of the continuation and is created from the
accepted milestone and current requested priorities. Do not interpret unchecked
gates as completed work. Existing data and uncommitted changes must be preserved.

1. Verify Docker, existing PostgreSQL and GPU access. **Verified** Docker/Compose
   and GPU enumeration. Existing PostgreSQL reachable, application user cannot
   create a database/schema; isolated container DB required for destructive tests.
2. Build production images, validate external-DB deployment and isolated synthetic
   stack. In progress. No existing DB reset or Docker volume deletion permitted.
3. Verify TLS, authentication, protected media, recorder progress, actual segments,
   playback and container recreation persistence.
4. Execute 4-camera smoke and progressively 8/16 only when CPU/RAM/disk permit.
   Larger tiers require suitable hardware; no registration-count capacity claims.
5. Run available 30-minute rotation/soak and controlled isolated failure tests;
   keep separate 2/8/24/72-hour configurations without claiming unrun results.
6. Resolve high security findings: authenticated media services, real worker
   heartbeat, recorder ownership/admission, migrations, bootstrap and retention.
7. Review every visible workflow; implement or clearly omit unsupported features.
8. Inventory exact artifacts/licenses, run dependency/security scans, preserve
   notices and document remaining legal/distribution obligations.
9. Produce a versioned candidate deployment package with setup/start/stop/status
   scripts, manifest/checksums and customer guides. No secrets or test footage.
10. Gate customer release on all required evidence, including physical CCTV
    validation (hardware currently unavailable) and clean-environment install.

Update PROJECT_STATUS.md and release evidence after meaningful phases. Final
classification must remain a candidate unless every required release gate passes.
