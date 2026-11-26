"""Store optional encrypted low-bandwidth RTSP substream sources."""

from alembic import op
from sqlalchemy import Column, String, inspect


revision = "0004_rtsp_preview"
down_revision = "0003_alerts"
branch_labels = None
depends_on = None


def upgrade():
    existing = {column["name"] for column in inspect(op.get_bind()).get_columns("rtsp_cameras")}
    if "preview_source_encrypted" not in existing:
        op.add_column("rtsp_cameras", Column("preview_source_encrypted", String(4096)))


def downgrade():
    raise NotImplementedError("Dropping preview source settings would lose camera configuration")
