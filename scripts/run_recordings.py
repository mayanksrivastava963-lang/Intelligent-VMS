"""Start the local recording API and worker using this Python environment."""

import getpass
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from backend.app.core.config import load_settings
from backend.app.database.session import create_database


def main():
    os.chdir(ROOT)
    load_dotenv(ROOT / ".env")
    if not os.getenv("VMS_OPERATOR_PASSWORD") and not os.getenv("VMS_OPERATOR_PASSWORD_HASH"):
        username = input("Admin ID [admin]: ").strip() or "admin"
        password = getpass.getpass("Choose an operator password for this session (12+ characters): ")
        if len(password) < 12:
            raise SystemExit("Password must contain at least 12 characters")
        os.environ["VMS_OPERATOR_USERNAME"] = username
        os.environ["VMS_OPERATOR_PASSWORD"] = password
    if not os.getenv("VMS_SESSION_SECRET"):
        os.environ["VMS_SESSION_SECRET"] = secrets.token_urlsafe(48)
    settings = load_settings()
    engine = create_database(settings["database_url"])
    engine.dispose()
    processes = []
    try:
        processes.append(subprocess.Popen([sys.executable, "-m", "services.recording_engine.worker"], cwd=ROOT))
        processes.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app",
                                           "--host", "127.0.0.1", "--port", "8000"], cwd=ROOT))
        print("API documentation: http://127.0.0.1:8000/docs\nStart the frontend separately with npm run dev.\nPress Ctrl+C to stop API and worker.")
        while all(process.poll() is None for process in processes):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
