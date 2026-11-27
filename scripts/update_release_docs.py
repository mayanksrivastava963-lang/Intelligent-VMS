"""Link current measured results while preserving historical milestone notes."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for name in ["PROJECT_STATUS.md", "PRODUCTION_MASTER_PLAN.md", "README.md", "THIRD_PARTY_NOTICES.md",
             "docs/PRODUCT_AUDIT.md", "docs/PRODUCT_RESEARCH.md", "docs/SYSTEM_ARCHITECTURE.md",
             "docs/PERFORMANCE_BENCHMARKS.md", "docs/HARDWARE_SIZING_GUIDE.md", "docs/SECURITY_REVIEW.md",
             "docs/TEST_REPORT.md", "docs/RELEASE_CHECKLIST.md", "docs/customer/OPERATIONS.md"]:
    path = root / name
    prefix_path = "../" if name.startswith("docs/customer/") else "" if name.startswith("docs/") else "docs/"
    prefix = f"""# Current update — 2026-11-27

**Internal release candidate; customer rollout remains blocked.** Actual Docker
builds/startup, HTTPS/authentication, saved recording range playback, external
PostgreSQL read-only access and duplicate-recorder rejection are verified.
The four-camera run hit the 90% RAM cutoff. No sustained capacity or 30-minute
rotation pass is claimed. Updated Python/frontend dependency audits report zero
advisories after Cryptography/Pillow upgrades; complete security and licensing
clearance remain open.

See [current measured evidence]({prefix_path}DEPLOYMENT_EVIDENCE.md) and
[current installation instructions]({prefix_path}DOCKER_DEPLOYMENT.md).
Use scripts/setup.ps1 then scripts/start.ps1 -Build for customer staging;
use scripts/start.ps1 -Validation for the existing isolated developer stack.
These replace the earlier Docker-unavailable, no-package and old Compose startup
instructions below. Recovery paths still require fault-injection validation.

---

## Earlier milestone record (historical; not current installation instructions)

"""
    original = path.read_text(encoding="utf-8")
    if not original.startswith("# Current update — 2026-11-27"):
        path.write_text(prefix + original, encoding="utf-8")
print("Updated mandatory documentation")
