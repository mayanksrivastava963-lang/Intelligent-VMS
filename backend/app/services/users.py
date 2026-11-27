import time
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from backend.app.core.security import hash_password
from backend.app.models.users import (
    audit_logs,
    permissions,
    role_permissions,
    roles,
    user_sessions,
    users,
)


ROLE_PERMISSIONS = {
    "super_administrator": {
        "camera.read", "camera.manage", "recording.read", "recording.manage",
        "user.read", "user.manage", "role.read", "role.manage", "health.read",
        "settings.manage", "alerts.read", "alerts.manage", "audit.read", "storage.read",
    },
    "administrator": {
        "camera.read", "camera.manage", "recording.read", "recording.manage",
        "user.read", "user.manage", "role.read", "health.read", "alerts.read",
        "alerts.manage", "storage.read",
    },
    "operator": {"camera.read", "recording.read", "health.read", "alerts.read"},
    "viewer": {"camera.read", "recording.read"},
}

ROLE_NAMES = {
    "super_administrator": "Super Administrator",
    "administrator": "Administrator",
    "operator": "Operator",
    "viewer": "Viewer",
}

PERMISSION_DESCRIPTIONS = {
    "camera.read": "View cameras and live feeds",
    "camera.manage": "Add, control, and remove cameras",
    "recording.read": "View and play recordings",
    "recording.manage": "Manage recordings",
    "user.read": "View user accounts",
    "user.manage": "Create and manage user accounts",
    "role.read": "View application roles",
    "role.manage": "Manage roles and permissions",
    "health.read": "View service health and system metrics",
    "settings.manage": "Change application settings",
    "alerts.read": "View alerts and events",
    "alerts.manage": "Review and acknowledge alerts",
    "audit.read": "View security audit events",
    "storage.read": "View storage utilization",
}


def _insert_ignore_conflict(connection, statement):
    try:
        with connection.begin_nested():
            connection.execute(statement)
            return True
    except IntegrityError:
        return False


def initialize_user_database(engine, username, password_hash, password=""):
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(1867087102)"))
        for role_id, display_name in ROLE_NAMES.items():
            if connection.execute(select(roles.c.id).where(roles.c.id == role_id)).first() is None:
                _insert_ignore_conflict(
                    connection,
                    roles.insert().values(id=role_id, display_name=display_name),
                )

        for permission_id, description in PERMISSION_DESCRIPTIONS.items():
            if connection.execute(select(permissions.c.id).where(permissions.c.id == permission_id)).first() is None:
                _insert_ignore_conflict(
                    connection,
                    permissions.insert().values(id=permission_id, description=description),
                )

        for role_id, permission_ids in ROLE_PERMISSIONS.items():
            for permission_id in permission_ids:
                existing = connection.execute(
                    select(role_permissions.c.role_id).where(
                        role_permissions.c.role_id == role_id,
                        role_permissions.c.permission_id == permission_id,
                    )
                ).first()
                if existing is None:
                    _insert_ignore_conflict(
                        connection,
                        role_permissions.insert().values(
                            role_id=role_id, permission_id=permission_id
                        ),
                    )

        # Configuration is a one-time bootstrap, never an account recovery API.
        existing_admin = connection.execute(select(users.c.id).limit(1)).first()
        if existing_admin is None:
            stored_hash = password_hash or hash_password(password)
            now = time.time()
            user_id = str(uuid4())
            inserted = _insert_ignore_conflict(
                connection,
                users.insert().values(
                    id=user_id,
                    full_name="System Administrator",
                    username=username.casefold(),
                    email=f"{username.casefold()}@local.invalid",
                    password_hash=stored_hash,
                    role_id="super_administrator",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
            )
            if inserted:
                add_audit(connection, "initial_admin_created", target_user_id=user_id)


def add_audit(connection, action, target_user_id=None, outcome="success", remote_address=None, actor_user_id=None):
    connection.execute(audit_logs.insert().values(
        id=str(uuid4()),
        actor_user_id=actor_user_id,
        action=action,
        target_user_id=target_user_id,
        outcome=outcome,
        remote_address=remote_address,
        created_at=time.time(),
    ))


def get_user_by_username(engine, username):
    with engine.connect() as connection:
        row = connection.execute(
            select(users, roles.c.display_name.label("role_name"))
            .join(roles, users.c.role_id == roles.c.id)
            .where(users.c.username == username.strip().casefold())
        ).mappings().first()
        return dict(row) if row else None


def get_user_by_session(engine, session_id, now=None):
    now = time.time() if now is None else now
    with engine.connect() as connection:
        row = connection.execute(
            select(users, roles.c.display_name.label("role_name"), user_sessions.c.id.label("session_id"))
            .join(roles, users.c.role_id == roles.c.id)
            .join(user_sessions, user_sessions.c.user_id == users.c.id)
            .where(user_sessions.c.id == session_id, user_sessions.c.expires_at > now, users.c.is_active.is_(True))
        ).mappings().first()
        if row is None:
            return None
        result = dict(row)
        result["permissions"] = get_role_permissions(connection, result["role_id"])
        return result


def get_role_permissions(connection, role_id):
    rows = connection.execute(
        select(role_permissions.c.permission_id)
        .where(role_permissions.c.role_id == role_id)
        .order_by(role_permissions.c.permission_id)
    )
    return [row[0] for row in rows]


def list_users(engine):
    with engine.connect() as connection:
        rows = connection.execute(
            select(users, roles.c.display_name.label("role_name"))
            .join(roles, users.c.role_id == roles.c.id)
            .order_by(users.c.created_at.desc())
        ).mappings()
        return [public_user(dict(row)) for row in rows]


def list_roles(engine):
    with engine.connect() as connection:
        rows = connection.execute(select(roles).order_by(roles.c.id)).mappings()
        result = []
        for row in rows:
            item = dict(row)
            item["permissions"] = get_role_permissions(connection, item["id"])
            result.append(item)
        return result


def list_audit_logs(engine, limit=100):
    with engine.connect() as connection:
        rows = connection.execute(
            select(audit_logs, users.c.username.label("actor_username"))
            .outerjoin(users, audit_logs.c.actor_user_id == users.c.id)
            .order_by(audit_logs.c.created_at.desc())
            .limit(limit)
        ).mappings()
        return [dict(row) for row in rows]


def public_user(row):
    return {
        "id": row["id"],
        "full_name": row["full_name"],
        "username": row["username"],
        "email": row["email"],
        "role_id": row["role_id"],
        "role_name": row["role_name"],
        "is_active": row["is_active"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_login_at": row["last_login_at"],
    }
