import time
from uuid import uuid4

from sqlalchemy import delete, func, select, update

from backend.app.models.recordings import cameras, segments, videos


def list_videos(engine, limit=100, offset=0, camera_id=None, query_text=None):
    with engine.connect() as connection:
        query = select(videos)
        if camera_id:
            query = query.where(videos.c.camera_id == camera_id)
        if query_text:
            query = query.where(videos.c.filename.ilike(f"%{query_text.strip()}%"))
        rows = connection.execute(
            query.order_by(videos.c.created_at.desc()).limit(limit).offset(offset)
        )
        return [public_video(dict(row)) for row in rows.mappings()]


def public_video(row):
    row.pop("lease_token", None)
    return row


def get_video(engine, video_id):
    with engine.connect() as connection:
        row = connection.execute(select(videos).where(videos.c.id == video_id)).mappings().first()
        if row is None:
            return None
        result = public_video(dict(row))
        rows = connection.execute(select(segments).where(segments.c.video_id == video_id).order_by(segments.c.number))
        result["segments"] = []
        for item in rows.mappings():
            segment = dict(item)
            segment.pop("relative_path")
            segment["playback_url"] = f"/api/segments/{segment['id']}/content"
            result["segments"].append(segment)
        return result


def recover_stale_jobs(engine, now=None):
    now = time.time() if now is None else now
    with engine.begin() as connection:
        stale = (videos.c.status == "processing") & (videos.c.updated_at < now - 90)
        connection.execute(update(videos).where(stale, videos.c.attempts < 3).values(
            status="queued", progress=0, lease_token=None, updated_at=now))
        connection.execute(update(videos).where(stale, videos.c.attempts >= 3).values(
            status="failed", error="Worker interrupted repeatedly. Retry after checking worker health.",
            lease_token=None, updated_at=now))
        connection.execute(update(videos).where(videos.c.status == "uploading", videos.c.updated_at < now - 3600).values(
            status="failed", error="Upload interrupted. Upload the file again.", updated_at=now))


def claim_job(engine):
    with engine.begin() as connection:
        query = select(videos).where(videos.c.status == "queued").order_by(videos.c.created_at).limit(1)
        if engine.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        row = connection.execute(query).mappings().first()
        if row is None:
            return None
        job = dict(row)
        token = str(uuid4())
        claimed = connection.execute(update(videos).where(videos.c.id == job["id"], videos.c.status == "queued").values(
            status="processing", lease_token=token, updated_at=time.time(), attempts=videos.c.attempts + 1,
            progress=0, error=None))
        if claimed.rowcount != 1:
            return None
        job["lease_token"] = token
        return job


def heartbeat(engine, job, progress, duration):
    with engine.begin() as connection:
        result = connection.execute(update(videos).where(
            videos.c.id == job["id"], videos.c.status == "processing",
            videos.c.lease_token == job["lease_token"]).values(
                updated_at=time.time(), progress=min(99, max(0, progress)), duration_seconds=duration))
        return result.rowcount == 1


def complete_job(engine, job, rows, duration):
    with engine.begin() as connection:
        updated = connection.execute(update(videos).where(
            videos.c.id == job["id"], videos.c.lease_token == job["lease_token"],
            videos.c.status == "processing").values(
                status="ready", progress=100, duration_seconds=duration, updated_at=time.time(), lease_token=None))
        if updated.rowcount != 1:
            raise RuntimeError("Worker lease lost")
        connection.execute(delete(segments).where(segments.c.video_id == job["id"]))
        connection.execute(segments.insert(), rows)


def fail_job(engine, job, message):
    with engine.begin() as connection:
        connection.execute(update(videos).where(
            videos.c.id == job["id"], videos.c.lease_token == job["lease_token"]).values(
                status="failed", error=message, updated_at=time.time(), lease_token=None))


def list_cameras(engine, limit=None, offset=0):
    with engine.connect() as connection:
        query = (
            select(cameras, videos.c.filename, videos.c.duration_seconds)
            .join(videos, cameras.c.video_id == videos.c.id)
            .where(videos.c.status == "ready")
            .order_by(cameras.c.created_at)
        )
        if limit is not None:
            query = query.limit(limit).offset(offset)
        rows = connection.execute(query).mappings().all()
        video_ids = [row["video_id"] for row in rows]
        segments_by_video = {video_id: [] for video_id in video_ids}
        if video_ids:
            segment_rows = connection.execute(
                select(segments).where(segments.c.video_id.in_(video_ids))
                .order_by(segments.c.video_id, segments.c.number)
            ).mappings()
            for item in segment_rows:
                segment = dict(item)
                segment.pop("relative_path")
                segment["playback_url"] = f"/api/segments/{segment['id']}/content"
                segments_by_video[segment["video_id"]].append(segment)
        result = []
        for row in rows:
            camera = {
                "id": row["id"],
                "video_id": row["video_id"],
                "name": row["name"],
                "location": row["location"],
                "source_type": "virtual",
                "status": row["status"],
                "filename": row["filename"],
                "duration_seconds": row["duration_seconds"],
            }
            camera["segments"] = segments_by_video[camera["video_id"]]
            result.append(camera)
        return result


def count_cameras(engine):
    with engine.connect() as connection:
        return connection.execute(
            select(func.count()).select_from(cameras.join(videos))
            .where(videos.c.status == "ready")
        ).scalar_one()


def create_camera(engine, video_id, name, location=""):
    with engine.begin() as connection:
        video = connection.execute(
            select(videos).where(videos.c.id == video_id)
        ).mappings().first()
        if video is None or video["status"] != "ready":
            return None
        camera_id = str(uuid4())
        connection.execute(cameras.insert().values(
            id=camera_id,
            video_id=video_id,
            name=name,
            location=location,
            status="stopped",
            created_at=time.time(),
        ))
        return camera_id


def set_camera_status(engine, camera_id, status):
    with engine.begin() as connection:
        result = connection.execute(
            update(cameras).where(cameras.c.id == camera_id).values(status=status)
        )
        return result.rowcount == 1


def delete_camera(engine, camera_id):
    with engine.begin() as connection:
        result = connection.execute(delete(cameras).where(cameras.c.id == camera_id))
        return result.rowcount == 1


def set_video_protection(engine, video_id, protected):
    with engine.begin() as connection:
        result = connection.execute(
            update(videos).where(videos.c.id == video_id).values(protected=bool(protected))
        )
        return result.rowcount == 1
