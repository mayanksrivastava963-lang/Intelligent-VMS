import os
import ipaddress
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
        "internal_test_tools": False,
        "resource_thresholds": tuple(float(os.getenv("VMS_RESOURCE_" + level, default)) for level, default in
                                     (("WARN", "75"), ("REDUCE", "80"), ("BLOCK", "85"))),
        "resource_network_interface": os.getenv("VMS_NETWORK_INTERFACE", ""),
        "resource_hysteresis": float(os.getenv("VMS_RESOURCE_HYSTERESIS", "3")),
        "resource_network_mbps": float(os.getenv("VMS_NETWORK_MBPS", "0")),
        "resource_host_file": os.getenv("VMS_HOST_RESOURCE_FILE", ""),
        "resource_required_metrics": [v.strip() for v in os.getenv("VMS_REQUIRED_METRICS", "").split(",") if v.strip()],
        "ai_available": os.getenv("VMS_AI_AVAILABLE", "false").lower() == "true",
        "max_recorders": int(os.getenv("VMS_MAX_RECORDERS", "16")),
        "camera_networks": [item.strip() for item in os.getenv("VMS_CAMERA_NETWORKS", "").split(",") if item.strip()],
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
        "retention_cycle_seconds": int(os.getenv("RETENTION_CYCLE_SECONDS", "3600")),
        "recorder_id": os.getenv("VMS_RECORDER_ID", "primary").strip() or "primary",
        "recorder_mode": os.getenv("VMS_RECORDER_MODE", "single").strip().lower(),
        "recorder_shard_index": int(os.getenv("RECORDER_SHARD_INDEX", "0")),
        "recorder_shard_total": int(os.getenv("RECORDER_SHARD_TOTAL", "1")),
        "recorder_takeover_seconds": int(os.getenv("RECORDER_TAKEOVER_SECONDS", "30")),
        "max_admitted_cameras": int(os.getenv("VMS_MAX_ADMITTED_CAMERAS") or os.getenv("VMS_MAX_RECORDERS", "16")),
        "ai_device": os.getenv("AI_DEVICE", "auto").strip().lower(),
        "ai_gpu_memory_fraction": float(os.getenv("AI_GPU_MEMORY_FRACTION", "0")),
        "ai_batch_size": int(os.getenv("AI_BATCH_SIZE", "4")),
        "ai_max_cameras": int(os.getenv("AI_MAX_CAMERAS", "4")),
        "ai_shard_index": int(os.getenv("AI_SHARD_INDEX", "0")),
        "ai_shard_total": int(os.getenv("AI_SHARD_TOTAL", "1")),
        "loitering_threshold": int(os.getenv("LOITERING_THRESHOLD_SECONDS", "1800")),
        "unattended_threshold": int(os.getenv("UNATTENDED_OBJECT_THRESHOLD_SECONDS", "1800")),
        "unattended_distance": int(os.getenv("UNATTENDED_DISTANCE_PIXELS", "80")),
    }
    if settings["mediamtx_api_url"] and not settings["mediamtx_api_password"]:
        raise RuntimeError("Set MEDIAMTX_API_PASSWORD when MEDIAMTX_API_URL is enabled")
    for network in settings["camera_networks"]:
        ipaddress.ip_network(network)
    if settings["max_recorders"] < 1:
        raise RuntimeError("VMS_MAX_RECORDERS must be positive; this is an admission limit, not certified capacity")
    warn, reduce, block = settings["resource_thresholds"]
    if not 0 < warn < reduce < block <= 100:
        raise RuntimeError("Require 0 < resource warning < reduction < admission block <= 100")
    if not 0 <= settings["resource_hysteresis"] < warn:
        raise RuntimeError("Invalid resource recovery hysteresis")
    if settings["resource_network_mbps"] < 0 or any(k not in {"cpu", "ram", "gpu", "vram", "storage", "network"} for k in settings["resource_required_metrics"]):
        raise RuntimeError("Invalid resource monitoring configuration")
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
    if settings["retention_cycle_seconds"] < 60:
        raise RuntimeError("RETENTION_CYCLE_SECONDS must be at least 60")
    if settings["recorder_mode"] not in {"single", "distributed"}:
        raise RuntimeError("VMS_RECORDER_MODE must be single or distributed")
    if settings["recorder_shard_total"] < 1 or not 0 <= settings["recorder_shard_index"] < settings["recorder_shard_total"]:
        raise RuntimeError("Invalid recorder shard configuration")
    if settings["recorder_takeover_seconds"] < 10:
        raise RuntimeError("RECORDER_TAKEOVER_SECONDS must be at least 10")
    if settings["ai_device"] not in {"auto", "cpu", "cuda"}:
        raise RuntimeError("AI_DEVICE must be auto, cpu, or cuda")
    if not 0 <= settings["ai_gpu_memory_fraction"] <= 1:
        raise RuntimeError("AI_GPU_MEMORY_FRACTION must be between 0 and 1")
    if settings["ai_batch_size"] < 1 or settings["ai_max_cameras"] < 1:
        raise RuntimeError("Invalid AI batch or camera limit")
    if settings["ai_shard_total"] < 1 or not 0 <= settings["ai_shard_index"] < settings["ai_shard_total"]:
        raise RuntimeError("Invalid AI shard configuration")
    if min(settings["loitering_threshold"], settings["unattended_threshold"], settings["unattended_distance"]) < 1:
        raise RuntimeError("Invalid AI rule threshold")
    storage.mkdir(parents=True, exist_ok=True)
    return settings
