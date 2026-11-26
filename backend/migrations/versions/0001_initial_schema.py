"""Baseline the existing VMS schema and add the RTSP creation index."""

from alembic import op
from sqlalchemy import inspect

from backend.app.models.recordings import metadata
from backend.app.models import users  # Register auth tables.


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    metadata.create_all(connection, checkfirst=True)
    existing = {index["name"] for index in inspect(connection).get_indexes("rtsp_cameras")}
    if "ix_rtsp_cameras_created_at" not in existing:
        op.create_index("ix_rtsp_cameras_created_at", "rtsp_cameras", ["created_at"])


def downgrade():
    raise NotImplementedError("The baseline migration cannot safely remove pre-existing VMS data")
