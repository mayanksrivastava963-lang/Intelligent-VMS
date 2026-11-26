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
        "mediamtx_api_url": os.getenv("MEDIAMTX_API_URL", ""),
        "mediamtx_api_user": os.getenv("MEDIAMTX_API_USER", "vms-api"),
        "mediamtx_api_password": os.getenv("MEDIAMTX_API_PASSWORD", ""),
        "redis_url": os.getenv("REDIS_URL", ""),
        "trusted_proxy_cidrs": [item.strip() for item in os.getenv("VMS_TRUSTED_PROXY_CIDRS", "").split(",") if item.strip()],
        "db_pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
        "db_max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "5")),
        "db_pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
        "mediamtx_rtsp_url": os.getenv("MEDIAMTX_RTSP_URL", "rtsp://mediamtx:8554"),
        "retention_days": int(os.getenv("RECORDING_RETENTION_DAYS", "30")),
        "retention_free_high_bytes": int(os.getenv("RETENTION_FREE_HIGH_BYTES", str(11 * 1024**3))),
        "ai_batch_size": int(os.getenv("AI_BATCH_SIZE", "4")),
        "ai_max_cameras": int(os.getenv("AI_MAX_CAMERAS", "4")),
        "loitering_threshold": int(os.getenv("LOITERING_THRESHOLD_SECONDS", "1800")),
        "unattended_threshold": int(os.getenv("UNATTENDED_OBJECT_THRESHOLD_SECONDS", "1800")),
        "unattended_distance": int(os.getenv("UNATTENDED_DISTANCE_PIXELS", "80")),
    }
    if settings["mediamtx_api_url"] and not settings["mediamtx_api_password"]:
        raise RuntimeError("Set MEDIAMTX_API_PASSWORD when MEDIAMTX_API_URL is enabled")
    for key in ("max_upload_bytes", "segment_seconds", "job_timeout_seconds", "ffmpeg_threads"):
        if settings[key] < 1:
            raise RuntimeError(f"{key} must be positive")
    if settings["min_free_bytes"] < 0:
        raise RuntimeError("min_free_bytes must not be negative")
    if settings["ai_sample_interval_ms"] < 1000:
        raise RuntimeError("ai_sample_interval_ms must be at least 1000")
    if settings["db_pool_size"] < 1 or settings["db_max_overflow"] < 0 or settings["db_pool_recycle"] < 1:
        raise RuntimeError("Invalid database pool settings")
    if settings["retention_days"] < 1 or settings["retention_free_high_bytes"] < settings["min_free_bytes"]:
        raise RuntimeError("Invalid retention settings")
    if not 1 <= settings["ai_batch_size"] <= 8 or not 1 <= settings["ai_max_cameras"] <= 256:
        raise RuntimeError("Invalid AI batch or camera limit")
    if min(settings["loitering_threshold"], settings["unattended_threshold"], settings["unattended_distance"]) < 1:
        raise RuntimeError("Invalid AI rule threshold")
    storage.mkdir(parents=True, exist_ok=True)
    return settings
