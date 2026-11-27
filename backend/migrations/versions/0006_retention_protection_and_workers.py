"""Add legal-hold video protection and distributed recorder worker status table."""

from alembic import op
from sqlalchemy import Boolean, Column, false, inspect

from backend.app.models.recordings import recorder_workers


revision = "0006_retention_workers"
down_revision = "0005_camera_ai_and_video_camera"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("recording_videos")}
    if "protected" not in columns:
        op.add_column(
            "recording_videos",
            Column("protected", Boolean, nullable=False, server_default=false()),
        )
    if not inspector.has_table("recorder_workers"):
        recorder_workers.create(bind)


def downgrade():
    raise NotImplementedError("Removing protection metadata could expose protected footage to retention cleanup")
