import asyncio
import json
import ipaddress
import os
import re
import shutil
import time
from contextlib import asynccontextmanager
from urllib.parse import unquote
from uuid import uuid4
from threading import BoundedSemaphore, Lock

import anyio
import psutil
from redis import Redis, RedisError
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from backend.app.core.config import load_settings
from backend.app.services.system_metrics import read_system_metrics
from backend.app.services.login_limiter import LoginLimiter
from backend.app.services.camera_ai import (InvalidFrame, detect_jpeg, enabled_camera_ids,
                                            is_enabled, remove_camera_setting, set_enabled)
from backend.app.services.rtsp import (MediaMTXHub, StreamHub, create_rtsp_camera, get_rtsp_camera,
                                       list_rtsp_cameras, public_camera, update_rtsp_camera,
                                       valid_rtsp_url)
from backend.app.database.session import create_database
from backend.app.core.security import hash_password, password_needs_rehash, verify_password
from backend.app.models.recordings import alerts, cameras, segments, videos
from backend.app.models.users import audit_logs, user_sessions, users as users_table
from backend.app.services.recordings import (
    create_camera,
    count_cameras,
    delete_camera,
    get_video,
    list_cameras,
    list_videos,
    set_camera_status,
)
from backend.app.services.users import (
    ROLE_NAMES,
    add_audit,
    get_user_by_session,
    get_user_by_username,
    initialize_user_database,
    list_audit_logs,
    list_roles,
    list_users,
    public_user,
)


COOKIE = "vms_session"
ALLOWED_EXTENSIONS = {"mp4", "mov", "mkv", "avi", "webm", "m4v"}


def client_address(request):
    address = request.client.host if request.client else "unknown"
    try:
        client_ip = ipaddress.ip_address(address)
        for cidr in request.app.state.settings.get("trusted_proxy_cidrs", []):
            if client_ip in ipaddress.ip_network(cidr):
                forwarded = request.headers.get("x-real-ip", "")
                return str(ipaddress.ip_address(forwarded)) if forwarded else address
    except ValueError:
        pass
    return address


class CameraRequest(BaseModel):
    video_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=120)
    location: str = Field(default="", max_length=200)


class RTSPCameraRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    location: str = Field(default="", max_length=200)
    url: str = Field(repr=False)
    preview_url: str = Field(default="", repr=False)


class CameraAIRequest(BaseModel):
    enabled: bool


class UserCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    username: str = Field(min_length=3, max_length=64)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=12, max_length=256)
    role_id: str = Field(min_length=1, max_length=40)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(default=None, min_length=5, max_length=254)
    role_id: str | None = Field(default=None, min_length=1, max_length=40)
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=12, max_length=256)


def create_app(settings=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings or load_settings()
        if not app.state.settings.get("operator_password_hash"):
            app.state.settings["operator_password_hash"] = hash_password(
                app.state.settings["password"]
            )
        app.state.engine = create_database(
            app.state.settings["database_url"],
            app.state.settings.get("db_pool_size", 5),
            app.state.settings.get("db_max_overflow", 5),
            app.state.settings.get("db_pool_recycle", 1800),
        )
        media_url = app.state.settings.get("mediamtx_api_url")
        if media_url:
            app.state.stream_hub = MediaMTXHub(
                app.state.engine, app.state.settings["session_secret"], media_url,
                app.state.settings["mediamtx_api_user"],
                app.state.settings["mediamtx_api_password"],
            )
        else:
            app.state.stream_hub = StreamHub(app.state.engine, app.state.settings["session_secret"])
        initialize_user_database(
            app.state.engine,
            app.state.settings["operator_username"],
            app.state.settings["operator_password_hash"],
            app.state.settings.get("password", ""),
        )
        app.state.signer = URLSafeTimedSerializer(app.state.settings["session_secret"], salt="vms-operator")
        app.state.login_limiter = LoginLimiter(app.state.settings.get("redis_url"))
        app.state.ai_results = (Redis.from_url(app.state.settings["redis_url"],
                                                socket_connect_timeout=2, socket_timeout=2)
                                if app.state.settings.get("redis_url") else None)
        app.state.metrics_lock = Lock()
        app.state.inference_slot = BoundedSemaphore(1)
        app.state.ai_sample_lock = Lock()
        app.state.ai_sample_times = {}
        app.state.metrics_cache = None
        app.state.metrics_sample_time = 0
        app.state.dummy_password_hash = hash_password(os.urandom(32).hex())
        for camera in list_rtsp_cameras(app.state.engine):
            if camera["status"] == "running":
                try:
                    app.state.stream_hub.start(camera["id"])
                except RuntimeError:
                    pass
        try:
            yield
        finally:
            app.state.stream_hub.close()
            app.state.engine.dispose()

    app = FastAPI(title="Intelligent VMS API", lifespan=lifespan, redoc_url=None)

    @app.exception_handler(RequestValidationError)
    async def hide_validation_input(_request, _error):
        # Pydantic's default 422 includes submitted field values, including RTSP credentials.
        return JSONResponse(status_code=422, content={"detail": "Invalid request fields"})

    def require_operator(request: Request):
        try:
            session = request.app.state.signer.loads(request.cookies.get(COOKIE, ""), max_age=8 * 3600)
            session_id = session.get("session_id")
            if not isinstance(session_id, str):
                raise BadSignature("Invalid session")
        except (BadSignature, SignatureExpired):
            raise HTTPException(401, "Please sign in") from None
        user = get_user_by_session(request.app.state.engine, session_id)
        if user is None:
            raise HTTPException(401, "Please sign in")
        request.state.user = user
        return user

    def require_permission(permission):
        def check_permission(request: Request):
            user = require_operator(request)
            if permission not in user["permissions"]:
                raise HTTPException(403, "You do not have permission for this action")
            return user
        return check_permission

    def require_write_header(request: Request):
        if request.headers.get("x-vms-request") != "1":
            raise HTTPException(403, "Missing request protection header")

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        if request.url.path == "/docs":
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; frame-ancestors 'none'"
        else:
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.get("/api/health")
    def health(request: Request):
        with request.app.state.engine.connect() as connection:
            connection.execute(select(1))
        return {"status": "ok"}

    @app.get("/api/system/metrics", dependencies=[Depends(require_permission("health.read"))])
    def system_metrics(request: Request):
        state = request.app.state
        with state.metrics_lock:
            if state.metrics_cache is None or time.monotonic() - state.metrics_sample_time >= 3:
                try:
                    state.metrics_cache = read_system_metrics(state.settings["storage"])
                except (OSError, psutil.Error):
                    raise HTTPException(503, "System metrics are temporarily unavailable") from None
                state.metrics_sample_time = time.monotonic()
            return state.metrics_cache

    @app.post("/api/auth/login", dependencies=[Depends(require_write_header)])
    async def login(request: Request, response: Response):
        address = client_address(request)
        try:
            allowed = request.app.state.login_limiter.allow(address)
        except RuntimeError:
            raise HTTPException(503, "Sign-in service is temporarily unavailable") from None
        if not allowed:
            raise HTTPException(429, "Too many sign-in attempts. Wait one minute.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1024:
                raise HTTPException(413, "Login request too large")
        try:
            credentials = json.loads(body)
            username = credentials.get("username", "")
            password = credentials.get("password", "")
        except (ValueError, AttributeError):
            raise HTTPException(400, "Invalid login request") from None
        if not isinstance(username, str) or not isinstance(password, str):
            raise HTTPException(400, "Invalid login request")
        user = get_user_by_username(request.app.state.engine, username)
        password_hash = user["password_hash"] if user else request.app.state.dummy_password_hash
        password_matches = verify_password(password, password_hash)
        if not user or not user["is_active"] or not password_matches:
            with request.app.state.engine.begin() as connection:
                add_audit(connection, "login_failed", outcome="invalid_credentials", remote_address=address)
            raise HTTPException(401, "Incorrect username or password")
        request.app.state.login_limiter.clear(address)
        now = time.time()
        session_id = str(uuid4())
        if password_needs_rehash(password_hash):
            password_hash = hash_password(password)
        with request.app.state.engine.begin() as connection:
            if user["password_hash"] != password_hash:
                connection.execute(update(users_table).where(users_table.c.id == user["id"]).values(
                    password_hash=password_hash, updated_at=now
                ))
            connection.execute(update(users_table).where(users_table.c.id == user["id"]).values(
                last_login_at=now, updated_at=now
            ))
            connection.execute(user_sessions.insert().values(
                id=session_id, user_id=user["id"], created_at=now, expires_at=now + 8 * 3600
            ))
            add_audit(connection, "login_success", target_user_id=user["id"], remote_address=address,
                      actor_user_id=user["id"])
        response.set_cookie(COOKIE, request.app.state.signer.dumps({"session_id": session_id}),
                            httponly=True, secure=request.app.state.settings["secure_cookie"],
                            samesite="strict", max_age=8 * 3600)
        return {"authenticated": True}

    @app.get("/api/auth/session", dependencies=[Depends(require_operator)])
    def session(request: Request):
        config = request.app.state.settings
        user = request.state.user
        return {"authenticated": True, "id": user["id"], "username": user["username"],
                "full_name": user["full_name"], "role": user["role_id"],
                "role_name": user["role_name"], "permissions": user["permissions"],
                "segment_seconds": config["segment_seconds"],
                "max_upload_bytes": config["max_upload_bytes"],
                "ai_sample_interval_ms": config.get("ai_sample_interval_ms", 2000),
                "streaming_mode": "mediamtx" if config.get("mediamtx_api_url") else "mjpeg"}

    @app.post("/api/auth/logout", dependencies=[Depends(require_write_header), Depends(require_operator)])
    def logout(request: Request, response: Response):
        user = request.state.user
        session = request.app.state.signer.loads(request.cookies.get(COOKIE, ""), max_age=8 * 3600)
        with request.app.state.engine.begin() as connection:
            connection.execute(delete(user_sessions).where(user_sessions.c.id == session["session_id"]))
            remote_address = request.client.host if request.client else None
            add_audit(connection, "logout", target_user_id=user["id"], remote_address=remote_address,
                      actor_user_id=user["id"])
        response.delete_cookie(COOKIE)
        return {"authenticated": False}

    def can_manage_role(actor, target_role):
        return actor["role_id"] == "super_administrator" or target_role != "super_administrator"

    def validate_email(email):
        normalized = email.strip().casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
            raise HTTPException(400, "Enter a valid email address")
        return normalized

    @app.get("/api/users", dependencies=[Depends(require_permission("user.read"))])
    def users_index(request: Request):
        return list_users(request.app.state.engine)

    @app.post("/api/users", status_code=201, dependencies=[Depends(require_permission("user.manage")), Depends(require_write_header)])
    def create_user(body: UserCreate, request: Request):
        actor = request.state.user
        username = body.username.strip().casefold()
        if not re.fullmatch(r"[a-z0-9_.-]{3,64}", username):
            raise HTTPException(400, "Username must use 3-64 letters, numbers, dots, dashes, or underscores")
        if body.role_id not in ROLE_NAMES:
            raise HTTPException(400, "Choose a valid role")
        if not can_manage_role(actor, body.role_id):
            raise HTTPException(403, "You cannot assign the Super Administrator role")
        email = validate_email(body.email)
        user_id = str(uuid4())
        now = time.time()
        try:
            with request.app.state.engine.begin() as connection:
                connection.execute(users_table.insert().values(
                    id=user_id,
                    full_name=body.full_name.strip(),
                    username=username,
                    email=email,
                    password_hash=hash_password(body.password),
                    role_id=body.role_id,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ))
                add_audit(connection, "user_created", target_user_id=user_id, remote_address=request.client.host if request.client else None,
                          actor_user_id=actor["id"])
        except IntegrityError:
            raise HTTPException(409, "Username or email is already in use") from None
        return next(item for item in list_users(request.app.state.engine) if item["id"] == user_id)

    @app.patch("/api/users/{user_id}", dependencies=[Depends(require_permission("user.manage")), Depends(require_write_header)])
    def update_user(user_id: str, body: UserUpdate, request: Request):
        actor = request.state.user
        with request.app.state.engine.connect() as connection:
            target_row = connection.execute(select(users_table).where(users_table.c.id == user_id)).mappings().first()
        if target_row is None:
            raise HTTPException(404, "User not found")
        target = dict(target_row)
        if not can_manage_role(actor, target["role_id"]):
            raise HTTPException(403, "You cannot manage this administrator account")
        changes = body.model_dump(exclude_unset=True)
        if actor["id"] == user_id and ("role_id" in changes or changes.get("is_active") is False):
            raise HTTPException(400, "You cannot change your own role or deactivate yourself")
        if "role_id" in changes:
            if changes["role_id"] not in ROLE_NAMES:
                raise HTTPException(400, "Choose a valid role")
            if not can_manage_role(actor, changes["role_id"]):
                raise HTTPException(403, "You cannot assign the Super Administrator role")
        if "email" in changes:
            changes["email"] = validate_email(changes["email"])
        if "full_name" in changes:
            changes["full_name"] = changes["full_name"].strip()
        changes["updated_at"] = time.time()
        try:
            with request.app.state.engine.begin() as connection:
                connection.execute(update(users_table).where(users_table.c.id == user_id).values(**changes))
                if changes.get("is_active") is False:
                    connection.execute(delete(user_sessions).where(user_sessions.c.user_id == user_id))
                add_audit(connection, "user_updated", target_user_id=user_id,
                          remote_address=request.client.host if request.client else None,
                          actor_user_id=actor["id"])
        except IntegrityError:
            raise HTTPException(409, "Email address is already in use") from None
        return next(item for item in list_users(request.app.state.engine) if item["id"] == user_id)

    @app.post("/api/users/{user_id}/password", dependencies=[Depends(require_permission("user.manage")), Depends(require_write_header)])
    def reset_user_password(user_id: str, body: PasswordReset, request: Request):
        actor = request.state.user
        with request.app.state.engine.connect() as connection:
            target = connection.execute(select(users_table).where(users_table.c.id == user_id)).mappings().first()
        if target is None:
            raise HTTPException(404, "User not found")
        if not can_manage_role(actor, target["role_id"]):
            raise HTTPException(403, "You cannot manage this administrator account")
        now = time.time()
        with request.app.state.engine.begin() as connection:
            connection.execute(update(users_table).where(users_table.c.id == user_id).values(
                password_hash=hash_password(body.password), updated_at=now
            ))
            connection.execute(delete(user_sessions).where(user_sessions.c.user_id == user_id))
            add_audit(connection, "password_reset", target_user_id=user_id,
                      remote_address=request.client.host if request.client else None,
                      actor_user_id=actor["id"])
        return {"updated": True}

    @app.get("/api/roles", dependencies=[Depends(require_permission("role.read"))])
    def roles_index(request: Request):
        return list_roles(request.app.state.engine)

    @app.get("/api/audit-logs", dependencies=[Depends(require_permission("audit.read"))])
    def audit_index(request: Request, limit: int = 100):
        if not 1 <= limit <= 500:
            raise HTTPException(400, "Limit must be between 1 and 500")
        return list_audit_logs(request.app.state.engine, limit)

    @app.get("/api/videos", dependencies=[Depends(require_permission("recording.read"))])
    def index(request: Request, limit: int = 100, offset: int = 0):
        if not 1 <= limit <= 100 or offset < 0:
            raise HTTPException(400, "Invalid pagination")
        return list_videos(request.app.state.engine, limit, offset)

    @app.get("/api/videos/{video_id}", dependencies=[Depends(require_permission("recording.read"))])
    def detail(video_id: str, request: Request):
        result = get_video(request.app.state.engine, video_id)
        if result is None:
            raise HTTPException(404, "Recording not found")
        return result

    @app.post("/api/videos", status_code=202,
              dependencies=[Depends(require_permission("recording.manage")), Depends(require_write_header)])
    async def upload(request: Request):
        config = request.app.state.settings
        filename = unquote(request.headers.get("x-filename", ""))
        filename = filename.replace("\\", "/").split("/")[-1]
        if not filename or len(filename) > 240 or any(ord(char) < 32 for char in filename):
            raise HTTPException(400, "Provide a valid filename")
        if filename.rsplit(".", 1)[-1].lower() not in ALLOWED_EXTENSIONS:
            raise HTTPException(415, "Use MP4, MOV, MKV, AVI, WEBM or M4V")
        try:
            expected = int(request.headers.get("content-length", "0"))
        except ValueError:
            raise HTTPException(400, "Invalid content length") from None
        if expected < 0 or expected > config["max_upload_bytes"]:
            raise HTTPException(413, "Video exceeds the upload limit")
        if shutil.disk_usage(config["storage"]).free < expected + config["min_free_bytes"]:
            raise HTTPException(507, "Insufficient storage space")
        video_id = str(uuid4())
        folder = config["storage"] / video_id
        folder.mkdir()
        partial = folder / "source.part"
        engine = request.app.state.engine
        now = time.time()
        with engine.begin() as connection:
            connection.execute(videos.insert().values(id=video_id, filename=filename, status="uploading",
                bytes=0, created_at=now, updated_at=now, segment_seconds=config["segment_seconds"], progress=0, attempts=0))
        received = 0
        last_update = now
        try:
            async with await anyio.open_file(partial, "wb") as output:
                async for chunk in request.stream():
                    received += len(chunk)
                    if received > config["max_upload_bytes"]:
                        raise HTTPException(413, "Video exceeds the upload limit")
                    if shutil.disk_usage(config["storage"]).free < len(chunk) + config["min_free_bytes"]:
                        raise HTTPException(507, "Insufficient storage space")
                    await output.write(chunk)
                    if time.time() - last_update > 10:
                        last_update = time.time()
                        with engine.begin() as connection:
                            connection.execute(update(videos).where(videos.c.id == video_id).values(updated_at=last_update, bytes=received))
            if not received or (expected and received != expected):
                raise HTTPException(400, "Empty or incomplete upload")
            partial.replace(folder / "source")
            with engine.begin() as connection:
                connection.execute(update(videos).where(videos.c.id == video_id).values(
                    status="queued", bytes=received, updated_at=time.time()))
        except (Exception, asyncio.CancelledError):
            partial.unlink(missing_ok=True)
            (folder / "source").unlink(missing_ok=True)
            with engine.begin() as connection:
                connection.execute(update(videos).where(videos.c.id == video_id).values(
                    status="failed", error="Upload failed. Upload the file again.", updated_at=time.time()))
            raise
        return get_video(engine, video_id)

    @app.post("/api/videos/{video_id}/retry", dependencies=[Depends(require_permission("recording.manage")), Depends(require_write_header)])
    def retry(video_id: str, request: Request):
        engine = request.app.state.engine
        video = get_video(engine, video_id)
        if video is None:
            raise HTTPException(404, "Recording not found")
        if not (request.app.state.settings["storage"] / video["id"] / "source").is_file():
            raise HTTPException(409, "Source is unavailable. Upload the video again.")
        with engine.begin() as connection:
            result = connection.execute(update(videos).where(videos.c.id == video_id, videos.c.status == "failed").values(
                status="queued", error=None, progress=0, attempts=0, lease_token=None, updated_at=time.time()))
            if result.rowcount != 1:
                raise HTTPException(409, "Only failed jobs can be retried")
        return get_video(engine, video_id)

    @app.get("/api/cameras", dependencies=[Depends(require_permission("camera.read"))])
    def cameras_index(request: Request, limit: int = 100, offset: int = 0):
        if not 1 <= limit <= 500 or offset < 0:
            raise HTTPException(400, "Invalid pagination")
        enabled = enabled_camera_ids(request.app.state.engine)
        engine = request.app.state.engine
        virtual_total = count_cameras(engine)
        virtual_limit = max(0, min(limit, virtual_total - offset))
        virtual = list_cameras(engine, virtual_limit, offset) if virtual_limit else []
        physical_limit = limit - len(virtual)
        physical_offset = max(0, offset - virtual_total)
        physical = list_rtsp_cameras(engine, physical_limit, physical_offset) if physical_limit else []
        running_ids = [camera["id"] for camera in physical if camera["status"] == "running"]
        hub = request.app.state.stream_hub
        statuses = hub.statuses(running_ids) if isinstance(hub, MediaMTXHub) else None
        for camera in physical:
            if camera["status"] == "running":
                camera["connection_status"] = statuses[camera["id"]] if statuses is not None else hub.status(camera["id"])
        for camera in virtual + physical:
            camera["ai_enabled"] = camera["id"] in enabled
        return virtual + physical

    @app.get("/api/stream-access", dependencies=[Depends(require_permission("camera.read"))])
    def stream_access(request: Request):
        # Nginx auth_request passes the original URI; no media URLs or credentials leave the API.
        original = request.headers.get("x-original-uri", "")
        match = re.match(r"^/live(?:-webrtc)?/([0-9a-f-]{36})(?:-preview)?(?:/|\?|$)", original)
        if not match:
            raise HTTPException(403, "Stream access denied")
        camera = get_rtsp_camera(request.app.state.engine, match.group(1))
        if not camera or camera["status"] != "running":
            raise HTTPException(403, "Stream access denied")
        return Response(status_code=204)

    @app.post("/api/cameras/rtsp", status_code=201,
              dependencies=[Depends(require_permission("camera.manage")), Depends(require_write_header)])
    def add_rtsp_camera(body: RTSPCameraRequest, request: Request):
        if not body.name.strip() or len(body.url) > 2000 or not valid_rtsp_url(body.url):
            raise HTTPException(400, "Enter a camera name and a valid rtsp:// URL")
        if body.preview_url and (len(body.preview_url) > 2000 or not valid_rtsp_url(body.preview_url)):
            raise HTTPException(400, "Enter a valid rtsp:// substream URL")
        engine = request.app.state.engine
        camera_id = create_rtsp_camera(engine, request.app.state.settings["session_secret"],
                                       body.name.strip(), body.location.strip(), body.url, body.preview_url)
        return {**public_camera(get_rtsp_camera(engine, camera_id)), "ai_enabled": False}

    @app.get("/api/cameras/{camera_id}/stream", dependencies=[Depends(require_permission("camera.read"))])
    def camera_stream(camera_id: str, request: Request):
        engine = request.app.state.engine
        camera = get_rtsp_camera(engine, camera_id)
        if not camera:
            raise HTTPException(404, "Camera not found")
        if camera["status"] != "running":
            raise HTTPException(409, "Camera is stopped")
        if isinstance(request.app.state.stream_hub, MediaMTXHub):
            raise HTTPException(410, "Use the authenticated HLS live stream")
        signed_session = request.cookies.get(COOKIE, "")

        def session_valid():
            try:
                session = request.app.state.signer.loads(signed_session, max_age=8 * 3600)
                user = get_user_by_session(engine, session.get("session_id", ""))
                return bool(user and "camera.read" in user["permissions"])
            except (BadSignature, SignatureExpired):
                return False

        return StreamingResponse(request.app.state.stream_hub.frames(camera_id, session_valid),
                                 media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.post("/api/cameras", status_code=201,
              dependencies=[Depends(require_permission("camera.manage")), Depends(require_write_header)])
    def add_camera(body: CameraRequest, request: Request):
        name = body.name.strip()
        location = body.location.strip()
        if not name:
            raise HTTPException(400, "Camera name cannot be empty")
        camera_id = create_camera(request.app.state.engine, body.video_id, name, location)
        if camera_id is None:
            raise HTTPException(409, "Choose a recording that is ready to play")
        return {**next(camera for camera in list_cameras(request.app.state.engine) if camera["id"] == camera_id),
                "ai_enabled": False}

    @app.post("/api/cameras/{camera_id}/{action}", dependencies=[Depends(require_permission("camera.manage")), Depends(require_write_header)])
    def camera_action(camera_id: str, action: str, request: Request):
        if action not in {"start", "stop", "restart"}:
            raise HTTPException(404, "Camera action not found")
        status = "stopped" if action == "stop" else "running"
        engine = request.app.state.engine
        if get_rtsp_camera(engine, camera_id):
            update_rtsp_camera(engine, camera_id, status)
            hub = request.app.state.stream_hub
            try:
                if action == "stop":
                    hub.stop(camera_id)
                elif action == "restart":
                    hub.restart(camera_id)
                else:
                    hub.start(camera_id)
            except RuntimeError:
                update_rtsp_camera(engine, camera_id, "stopped")
                raise HTTPException(503, "Media server is temporarily unavailable") from None
            return {**public_camera(get_rtsp_camera(engine, camera_id), hub.status(camera_id)),
                    "ai_enabled": is_enabled(engine, camera_id)}
        if not set_camera_status(request.app.state.engine, camera_id, status):
            raise HTTPException(404, "Camera not found")
        camera = next(camera for camera in list_cameras(request.app.state.engine) if camera["id"] == camera_id)
        camera["ai_enabled"] = is_enabled(request.app.state.engine, camera_id)
        return camera

    @app.delete("/api/cameras/{camera_id}", dependencies=[Depends(require_permission("camera.manage")), Depends(require_write_header)])
    def remove_camera(camera_id: str, request: Request):
        state = request.app.state
        if update_rtsp_camera(request.app.state.engine, camera_id):
            try:
                state.stream_hub.stop(camera_id)
            except RuntimeError:
                pass
            remove_camera_setting(request.app.state.engine, camera_id)
            with state.ai_sample_lock:
                state.ai_sample_times.pop(camera_id, None)
            return {"deleted": True}
        if not delete_camera(request.app.state.engine, camera_id):
            raise HTTPException(404, "Camera not found")
        remove_camera_setting(request.app.state.engine, camera_id)
        with state.ai_sample_lock:
            state.ai_sample_times.pop(camera_id, None)
        return {"deleted": True}

    @app.put("/api/cameras/{camera_id}/ai",
             dependencies=[Depends(require_permission("camera.manage")), Depends(require_write_header)])
    def camera_ai_switch(camera_id: str, body: CameraAIRequest, request: Request):
        engine = request.app.state.engine
        if not get_rtsp_camera(engine, camera_id):
            with engine.connect() as connection:
                exists = connection.execute(select(cameras.c.id).where(cameras.c.id == camera_id)).first()
            if exists is None:
                raise HTTPException(404, "Camera not found")
        set_enabled(engine, camera_id, body.enabled)
        return {"camera_id": camera_id, "ai_enabled": body.enabled}

    @app.get("/api/cameras/{camera_id}/ai/detections",
             dependencies=[Depends(require_permission("camera.read"))])
    def latest_camera_detections(camera_id: str, request: Request):
        if not is_enabled(request.app.state.engine, camera_id):
            raise HTTPException(409, "AI is not enabled for this camera")
        redis = request.app.state.ai_results
        if redis is None:
            raise HTTPException(503, "AI worker is not configured")
        try:
            result = redis.get("vms:ai:" + camera_id)
        except RedisError:
            raise HTTPException(503, "AI results are temporarily unavailable") from None
        if result is None:
            return {"width": 0, "height": 0, "detections": [],
                    "processed_at": 0, "inference_ms": 0}
        return json.loads(result)

    @app.get("/api/alerts", dependencies=[Depends(require_permission("alerts.read"))])
    def alerts_index(request: Request, limit: int = 100, offset: int = 0, camera_id: str | None = None):
        if not 1 <= limit <= 100 or offset < 0:
            raise HTTPException(400, "Invalid pagination")
        query = select(alerts).order_by(alerts.c.occurred_at.desc()).limit(limit).offset(offset)
        if camera_id:
            query = query.where(alerts.c.camera_id == camera_id)
        with request.app.state.engine.connect() as connection:
            return [dict(row) for row in connection.execute(query).mappings()]

    @app.post("/api/alerts/{alert_id}/acknowledge",
              dependencies=[Depends(require_permission("alerts.manage")), Depends(require_write_header)])
    def acknowledge_alert(alert_id: str, request: Request):
        with request.app.state.engine.begin() as connection:
            result = connection.execute(update(alerts).where(
                alerts.c.id == alert_id, alerts.c.acknowledged_at.is_(None)
            ).values(acknowledged_at=time.time(), acknowledged_by=request.state.user["id"]))
            if result.rowcount != 1:
                raise HTTPException(404, "Unreviewed alert not found")
            add_audit(connection, "alert_acknowledged", actor_user_id=request.state.user["id"])
        return {"acknowledged": True}

    @app.post("/api/cameras/{camera_id}/ai/detections",
              dependencies=[Depends(require_permission("camera.read")), Depends(require_write_header)])
    async def camera_detections(camera_id: str, request: Request):
        if request.app.state.ai_results is not None:
            raise HTTPException(409, "Use the AI worker results endpoint")
        engine = request.app.state.engine
        camera = get_rtsp_camera(engine, camera_id)
        if camera is None:
            with engine.connect() as connection:
                camera = connection.execute(
                    select(cameras.c.status).where(cameras.c.id == camera_id)
                ).mappings().first()
        if camera is None:
            raise HTTPException(404, "Camera not found")
        if camera["status"] != "running" or not is_enabled(engine, camera_id):
            raise HTTPException(409, "Start the camera and enable AI first")
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 600_000:
                raise HTTPException(413, "Sample frame is too large")
        if not data:
            raise HTTPException(400, "JPEG frame is required")
        state = request.app.state
        with state.ai_sample_lock:
            now = time.monotonic()
            if now - state.ai_sample_times.get(camera_id, 0) < 1:
                raise HTTPException(429, "Wait before sending another AI sample")
            state.ai_sample_times[camera_id] = now
        if not state.inference_slot.acquire(blocking=False):
            raise HTTPException(429, "AI processor is busy")
        try:
            started = time.perf_counter()
            result = await anyio.to_thread.run_sync(detect_jpeg, bytes(data))
            result["processed_at"] = time.time()
            result["inference_ms"] = round((time.perf_counter() - started) * 1000, 1)
            return result
        except InvalidFrame as error:
            raise HTTPException(400, str(error)) from None
        except Exception:
            raise HTTPException(503, "AI processing is temporarily unavailable") from None
        finally:
            state.inference_slot.release()

    @app.get("/api/segments/{segment_id}/content", dependencies=[Depends(require_permission("recording.read"))])
    def content(segment_id: str, request: Request):
        if len(request.headers.get("range", "")) > 100 or "," in request.headers.get("range", ""):
            raise HTTPException(416, "Only a single byte range is supported")
        with request.app.state.engine.connect() as connection:
            row = connection.execute(select(segments).join(videos).where(
                segments.c.id == segment_id, videos.c.status == "ready")).mappings().first()
        if row is None:
            raise HTTPException(404, "Segment not found")
        root = request.app.state.settings["storage"].resolve()
        path = (root / row["relative_path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(404, "Segment file unavailable")
        return FileResponse(path, media_type="video/mp4", filename=f"segment-{row['number']:04d}.mp4",
                            content_disposition_type="inline")

    return app


app = create_app()
