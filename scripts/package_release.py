"""Create a source deployment candidate from explicit allowlists; never package local data."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0-rc3"
EXCLUDED_DIRS = {"__pycache__", ".pytest_cache", ".venv", "node_modules", "tests", "test-runs"}


def iter_folder_files(base: Path):
    for current, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        cur_path = Path(current)
        for name in files:
            yield cur_path / name


def main():
    target = ROOT / "releases" / ("Intelligent-VMS-" + VERSION)
    if target.exists():
        raise SystemExit("Candidate already exists; choose a new version rather than overwriting it")
    paths = {ROOT / p for p in (
        "compose.production.yml", "compose.host-monitor.yml", "compose.ai-gpu.yml",
        "compose.bundled-db.yml", "compose.valkey.yml", "compose.distributed-recorders.yml",
        ".dockerignore", ".env.example", "README.md", "PROJECT_STATUS.md",
        "PRODUCTION_MASTER_PLAN.md", "THIRD_PARTY_NOTICES.md",
        "backend/Dockerfile", "backend/requirements.txt", "backend/requirements.lock.txt",
        "backend/alembic.ini",
        "services/ai_engine/Dockerfile",
        "infrastructure/nginx/production.Dockerfile",
        "infrastructure/nginx/production.conf.template",
        "infrastructure/mediamtx/production.yml",
    )}
    for folder in ("backend/app", "backend/migrations", "services/recording_engine", "services/ai_engine", "frontend/src", "frontend/public", "docs", "deployment"):
        folder_path = ROOT / folder
        if folder_path.exists():
            paths.update(iter_folder_files(folder_path))
    paths.update(p for p in (ROOT / "frontend").iterdir() if p.is_file() and p.name in
                 {"package.json", "package-lock.json", "index.html", "tsconfig.json", "tsconfig.node.json", "vite.config.ts"})
    for name in ("setup.ps1", "start.ps1", "stop.ps1", "status.ps1", "deployment-common.ps1",
                 "backup_restore.ps1", "capacity_plan.py", "host_resources.py",
                 "rotation_test.py", "progressive_load_test.py"):
        paths.add(ROOT / "scripts" / name)
    manifest = []
    for source in sorted(paths):
        relative = source.relative_to(ROOT)
        is_secret_env = source.name == ".env" or (source.name.startswith(".env.") and source.name != ".env.example")
        if (EXCLUDED_DIRS.intersection(relative.parts)
                or source.suffix in {".pyc", ".pem", ".key", ".mp4", ".pt", ".onnx"}
                or is_secret_env):
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        manifest.append({"path": relative.as_posix(), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "bytes": source.stat().st_size})
    (target / "MANIFEST.json").write_text(json.dumps({"version": VERSION, "classification": "internal release candidate; customer rollout blocked", "files": manifest}, indent=2))
    archive = target.parent / (target.name + ".zip")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(target.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(target.parent))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (archive.parent / (archive.name + ".sha256")).write_text(digest + "  " + archive.name + "\n")
    print("Candidate:", archive)
    print("Files:", len(manifest), "SHA256:", digest)


if __name__ == "__main__":
    main()
