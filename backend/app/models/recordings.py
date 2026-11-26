from sqlalchemy import BigInteger, Column, Float, ForeignKey, Index, Integer, MetaData, String, Table, UniqueConstraint


metadata = MetaData()

videos = Table(
    "recording_videos", metadata,
    Column("id", String(36), primary_key=True),
    Column("filename", String(240), nullable=False),
    Column("status", String(20), nullable=False),
    Column("bytes", BigInteger, nullable=False, default=0),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
    Column("duration_seconds", Float),
    Column("segment_seconds", Integer, nullable=False),
    Column("progress", Float, nullable=False, default=0),
    Column("error", String(240)),
    Column("lease_token", String(36)),
    Column("attempts", Integer, nullable=False, default=0),
    Index("ix_recording_queue", "status", "created_at"),
)

segments = Table(
    "recording_segments", metadata,
    Column("id", String(36), primary_key=True),
    Column("video_id", String(36), ForeignKey("recording_videos.id", ondelete="CASCADE"), nullable=False),
    Column("number", Integer, nullable=False),
    Column("start_seconds", Float, nullable=False),
    Column("end_seconds", Float, nullable=False),
    Column("duration_seconds", Float, nullable=False),
    Column("bytes", BigInteger, nullable=False),
    Column("relative_path", String(200), nullable=False),
    UniqueConstraint("video_id", "number", name="uq_recording_segment_number"),
)

cameras = Table(
    "cameras", metadata,
    Column("id", String(36), primary_key=True),
    Column("video_id", String(36), ForeignKey("recording_videos.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(120), nullable=False),
    Column("location", String(200), nullable=False, default=""),
    Column("status", String(20), nullable=False, default="stopped"),
    Column("created_at", Float, nullable=False),
    Index("ix_cameras_video", "video_id"),
)

rtsp_cameras = Table(
    "rtsp_cameras", metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("location", String(200), nullable=False, default=""),
    Column("source_encrypted", String(4096), nullable=False),
    Column("status", String(20), nullable=False, default="stopped"),
    Column("created_at", Float, nullable=False),
)

camera_ai = Table(
    "camera_ai", metadata,
    Column("camera_id", String(36), primary_key=True),
    Column("enabled", Integer, nullable=False, default=0),
)
