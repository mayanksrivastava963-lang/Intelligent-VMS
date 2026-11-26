"""Persist recorder connection health and latest observed frame time."""

from alembic import op
from sqlalchemy import Column, Float, String, inspect


revision = "0002_rtsp_health"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    existing = {column["name"] for column in inspect(op.get_bind()).get_columns("rtsp_cameras")}
    if "health_status" not in existing:
        op.add_column("rtsp_cameras", Column("health_status", String(20), nullable=False, server_default="stopped"))
    if "last_frame_at" not in existing:
        op.add_column("rtsp_cameras", Column("last_frame_at", Float))


def downgrade():
    raise NotImplementedError("Removing recorder health columns would lose operational history")
