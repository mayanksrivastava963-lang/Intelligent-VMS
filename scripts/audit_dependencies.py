"""Run bounded Python/frontend audits and save reports without flooding the console."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "docs/release-evidence"
DEST.mkdir(parents=True, exist_ok=True)
command = ["docker", "run", "--rm", "--memory", "256m", "--cpus", "1", "-v",
           str(ROOT / "backend/requirements.lock.txt") + ":/tmp/requirements.txt:ro",
           "intelligent-vms-api:0.1.0", "sh", "-c",
           "pip install --quiet --target /tmp/audit pip-audit && PYTHONPATH=/tmp/audit python -m pip_audit -r /tmp/requirements.txt --disable-pip --no-deps --format json"]
result = subprocess.run(command, capture_output=True, text=True, timeout=240)
if result.returncode not in (0, 1):
    raise SystemExit("Audit tool failed; no clean result claimed")
report = json.loads(result.stdout)
(DEST / "python-audit.json").write_text(json.dumps(report, indent=2))
for package in report["dependencies"]:
    if package.get("vulns"):
        print(package["name"], package["version"], "advisories:", len(package["vulns"]),
              "fix versions:", sorted({v for issue in package["vulns"] for v in issue.get("fix_versions", [])}))
result = subprocess.run(["npm.cmd", "--prefix", str(ROOT / "frontend"), "audit", "--omit=dev", "--json"], capture_output=True, text=True, timeout=90)
report = json.loads(result.stdout)
(DEST / "javascript-audit.json").write_text(json.dumps(report, indent=2))
print("Frontend:", report["metadata"]["vulnerabilities"])
