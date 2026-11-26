from sqlalchemy import Boolean, Column, Float, ForeignKey, Index, String, Table

from backend.app.models.recordings import metadata


roles = Table(
    "roles",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("display_name", String(80), nullable=False, unique=True),
)

permissions = Table(
    "permissions",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("description", String(160), nullable=False),
)

role_permissions = Table(
    "role_permissions",
    metadata,
    Column("role_id", String(40), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", String(80), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)

users = Table(
    "users",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("full_name", String(120), nullable=False),
    Column("username", String(64), nullable=False, unique=True),
    Column("email", String(254), nullable=False, unique=True),
    Column("password_hash", String(512), nullable=False),
    Column("role_id", String(40), ForeignKey("roles.id"), nullable=False),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
    Column("last_login_at", Float),
    Index("ix_users_role", "role_id"),
)

user_sessions = Table(
    "user_sessions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
    Index("ix_user_sessions_expiry", "expires_at"),
)

audit_logs = Table(
    "audit_logs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("actor_user_id", String(36), ForeignKey("users.id", ondelete="SET NULL")),
    Column("action", String(80), nullable=False),
    Column("target_user_id", String(36), ForeignKey("users.id", ondelete="SET NULL")),
    Column("outcome", String(80), nullable=False),
    Column("remote_address", String(64)),
    Column("created_at", Float, nullable=False),
    Index("ix_audit_logs_created", "created_at"),
)
