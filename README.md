# Intelligent-VMS resource-aware source candidate

See [resource profiles and scaling](docs/RESOURCE_AND_SCALING.md) and
[current validation](docs/RESOURCE_VALIDATION.md). Laptop limits are testing
policy, not production ceilings. rc2 source is packaged separately; rebuilt rc2
images and deployment await safe host resource headroom. Prior deployment remains
available, with its earlier behavior. Do not treat source tests as a deployed guard.

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

# Intelligent-VMS

**Engineering hardening candidate. Customer release is blocked.**

Authenticated network-camera monitoring, shared MediaMTX distribution, independent
FFmpeg recording, segmented playback and optional AI are implemented. Real camera,
installation and sustained capacity validation remain outstanding.

Customer uploads and virtual-camera creation are removed. Historical footage is
preserved for authorized playback. Internal tests explicitly enable test-only APIs;
the normal entry point does not enable them.

Configure VMS_CAMERA_NETWORKS with approved CIDRs before starting cameras. Only
literal IP sources are accepted. Existing out-of-policy cameras stop on API startup.
Back up metadata, footage and the stable encryption/session secret before upgrades.

See [status](PROJECT_STATUS.md), [audit](docs/PRODUCT_AUDIT.md),
[test evidence](docs/TEST_REPORT.md), [release gates](docs/RELEASE_CHECKLIST.md),
and [candidate operations guide](docs/customer/OPERATIONS.md).

## Developer validation

Use the configured Python environment:

```text
python -m pytest backend/tests services/ai_engine/tests -q
npm --prefix frontend run build
python scripts/benchmark_metadata.py
python scripts/capacity_plan.py --cameras 16 --main-mbps 4
```

The metadata benchmark uses temporary rows and no active streams. Sizing results
are theoretical estimates. Old recording-workspace documents describe historical
upload workflows and are not current customer instructions. Docker/Nginx is the
intended deployment path; no supported installation is yet validated. Retention
requires explicit opt-in and further safety validation.
