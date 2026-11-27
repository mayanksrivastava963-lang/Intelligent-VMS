"""Inventory installed deployment artifacts without reading application secrets."""
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "docs/release-evidence"


def run(*args):
    return subprocess.check_output(args, text=True, encoding="utf-8")


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    code = "import importlib.metadata as m,json; print(json.dumps([dict(name=d.metadata['Name'],version=d.version,license=d.metadata.get('License-Expression') or d.metadata.get('License') or 'NOASSERTION') for d in m.distributions()]))"
    packages = json.loads(run("docker", "run", "--rm", "--network", "none", "intelligent-vms-api:0.1.0", "python", "-c", code))
    (DEST / "python-packages.json").write_text(json.dumps(packages, indent=2))
    (ROOT / "backend/requirements.lock.txt").write_text("# Resolved Linux container environment, 2026-11-27\n" +
        "\n".join(sorted(p["name"] + "==" + p["version"] for p in packages if p["name"].lower() != "pip")) + "\n")
    components = [{"type": "library", "name": p["name"], "version": p["version"],
                   "purl": f"pkg:pypi/{p['name'].lower() }@{p['version']}"} for p in packages]
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text())
    frontend = []
    for path, entry in lock["packages"].items():
        if not path:
            continue
        name = path.split("node_modules/")[-1]
        frontend.append(dict(name=name, version=entry.get("version"), license=entry.get("license", "NOASSERTION"),
                             dev=entry.get("dev", False)))
        components.append({"type": "library", "name": name, "version": entry.get("version", "unknown"),
                           "scope": "optional" if entry.get("dev") else "required"})
    (DEST / "javascript-packages.json").write_text(json.dumps(frontend, indent=2))
    images = ["intelligent-vms-api:0.1.0", "intelligent-vms-web:0.1.0", "redis:7-alpine", "bluenviron/mediamtx:1.21.4", "postgres:18-alpine"]
    identities = json.loads(run("docker", "image", "inspect", *images))
    identities = [{k: item[k] for k in ("Id", "RepoTags", "RepoDigests", "Architecture", "Os", "Size")} for item in identities]
    (DEST / "container-images.json").write_text(json.dumps(identities, indent=2))
    (DEST / "debian-packages.tsv").write_text(run("docker", "run", "--rm", "--network", "none", "intelligent-vms-api:0.1.0",
        "dpkg-query", "-W", "-f=${Package}\t${Version}\n"))
    (DEST / "ffmpeg-build.txt").write_text(run("docker", "run", "--rm", "--network", "none", "intelligent-vms-api:0.1.0", "ffmpeg", "-version"))
    sbom = {"bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": "urn:uuid:" + str(uuid4()), "version": 1,
            "metadata": {"timestamp": datetime.now(timezone.utc).isoformat(), "component": {"type": "application", "name": "Intelligent-VMS", "version": "0.1.0-rc1"}},
            "components": components}
    (DEST / "sbom.cdx.json").write_text(json.dumps(sbom, indent=2))
    print("Inventory and partial CycloneDX SBOM written; OS packages are a separate inventory, not complete license clearance.")


if __name__ == "__main__":
    main()
