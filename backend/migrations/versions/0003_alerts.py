"""Add reviewable AI alerts."""

from alembic import op
from sqlalchemy import inspect

from backend.app.models.recordings import alerts


revision = "0003_alerts"
down_revision = "0002_rtsp_health"
branch_labels = None
depends_on = None


def upgrade():
    if not inspect(op.get_bind()).has_table("alerts"):
        alerts.create(op.get_bind())


def downgrade():
    raise NotImplementedError("Dropping alerts would erase operator review history")
