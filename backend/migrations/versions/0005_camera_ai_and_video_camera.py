"""Ensure camera_ai table exists and add camera_id indexing to recording_videos."""

from alembic import op
from sqlalchemy import Column, String, inspect

from backend.app.models.recordings import camera_ai


revision = "0005_camera_ai_and_video_camera"
down_revision = "0004_rtsp_preview"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("camera_ai"):
        camera_ai.create(bind)
    columns = {column["name"] for column in inspector.get_columns("recording_videos")}
    if "camera_id" not in columns:
        op.add_column("recording_videos", Column("camera_id", String(36)))
    indexes = {index["name"] for index in inspector.get_indexes("recording_videos")}
    if "ix_recording_videos_camera_id" not in indexes:
        op.create_index("ix_recording_videos_camera_id", "recording_videos", ["camera_id", "created_at"])


def downgrade():
    raise NotImplementedError("Removing camera tracking metadata would break playback history filtering")
