import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL


ROOT = Path(__file__).resolve().parents[3]


def load_settings():
    load_dotenv(ROOT / ".env", override=False)
    storage = Path(os.getenv("RECORDING_STORAGE_PATH", str(ROOT / "storage" / "recordings"))).resolve()
    username = os.getenv("VMS_OPERATOR_USERNAME", "admin").strip()
    password = os.getenv("VMS_OPERATOR_PASSWORD", "")
    password_hash = os.getenv("VMS_OPERATOR_PASSWORD_HASH", "").strip()
    secret = os.getenv("VMS_SESSION_SECRET", "")
    if not username or len(username) > 64:
        raise RuntimeError("Set a valid VMS_OPERATOR_USERNAME (1-64 characters)")
    if not password_hash and len(password) < 12:
        raise RuntimeError("Set VMS_OPERATOR_PASSWORD (12+ characters) or VMS_OPERATOR_PASSWORD_HASH")
    if len(secret) < 32:
        raise RuntimeError("Set VMS_SESSION_SECRET (32+ characters)")
    database_url = os.getenv("DATABASE_URL")
    if not database_url and os.getenv("RECORDING_DATABASE") == "postgres":
        database_url = URL.create("postgresql+psycopg", username=os.environ["POSTGRES_USER"],
                                  password=os.environ["POSTGRES_PASSWORD"],
                                  host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
                                  port=int(os.getenv("POSTGRES_PORT", "5432")), database=os.environ["POSTGRES_DB"])
    if not database_url:
        database_url = "sqlite:///" + (ROOT / "storage" / "recordings.db").as_posix()
    settings = {
        "storage": storage,
        "database_url": database_url,
        "operator_username": username,
        "operator_password": password,
        "operator_password_hash": password_hash,
        "session_secret": secret,
        "secure_cookie": os.getenv("VMS_SECURE_COOKIE", "false").lower() == "true",
        "max_upload_bytes": int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024**3))),
        "min_free_bytes": int(os.getenv("MIN_FREE_BYTES", str(1024**3))),
        "segment_seconds": int(os.getenv("RECORDING_SEGMENT_SECONDS", "1800")),
        "job_timeout_seconds": int(os.getenv("JOB_TIMEOUT_SECONDS", "86400")),
        "ffmpeg_threads": int(os.getenv("FFMPEG_THREADS", "2")),
        "ai_sample_interval_ms": int(os.getenv("AI_SAMPLE_INTERVAL_MS", "2000")),
        "frontend_dist": Path(os.getenv("FRONTEND_DIST", str(ROOT / "frontend" / "dist"))),
    }
    for key in ("max_upload_bytes", "segment_seconds", "job_timeout_seconds", "ffmpeg_threads"):
        if settings[key] < 1:
            raise RuntimeError(f"{key} must be positive")
    if settings["min_free_bytes"] < 0:
        raise RuntimeError("min_free_bytes must not be negative")
    if settings["ai_sample_interval_ms"] < 1000:
        raise RuntimeError("ai_sample_interval_ms must be at least 1000")
    storage.mkdir(parents=True, exist_ok=True)
    return settings
