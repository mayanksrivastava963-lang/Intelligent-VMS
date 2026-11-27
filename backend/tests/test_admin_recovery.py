"""Offline recovery must update only the intended administrator and revoke sessions."""

import sys
from importlib import import_module

from sqlalchemy import select

from backend.app.core.security import hash_password, verify_password
from backend.app.database.session import create_database
from backend.app.models.users import audit_logs, user_sessions, users
from backend.app.services import admin_recovery
from backend.app.services.users import initialize_user_database


def test_short_recovery_password_is_validation_only():
    allowed = admin_recovery.password_allowed
    short_password = "a" * 4
    assert not allowed(short_password, "intelligent_vms_validation_test", "validation-admin")
    assert allowed(short_password, "intelligent_vms_validation_test", "validation-admin", True)
    assert not allowed(short_password, "intelligent_vms_production", "validation-admin", True)
    assert not allowed(short_password, "intelligent_vms_validation_test", "production-admin", True)
    assert allowed("long-password-123", "intelligent_vms_production", "production-admin")


def test_admin_recovery_revokes_sessions_and_records_audit(tmp_path, monkeypatch):
    engine = create_database("sqlite:///" + (tmp_path / "recovery.db").as_posix())
    initialize_user_database(engine, "admin", hash_password("old-password-123"))
    with engine.begin() as connection:
        user_id = connection.execute(select(users.c.id)).scalar_one()
        connection.execute(user_sessions.insert().values(
            id="old-session", user_id=user_id, created_at=1, expires_at=9999999999
        ))

    monkeypatch.setattr(admin_recovery, "load_settings", lambda: {
        "database_url": str(engine.url), "operator_username": "admin",
        "operator_password": "old-password-123",
    })
    monkeypatch.setattr(admin_recovery, "create_database", lambda _: engine)
    monkeypatch.setattr(admin_recovery.getpass, "getpass", lambda _: "new-password-123")
    monkeypatch.setattr(sys, "argv", ["admin_recovery", "reset"])
    admin_recovery.main()

    with engine.connect() as connection:
        assert verify_password("new-password-123", connection.execute(select(users.c.password_hash)).scalar_one())
        assert connection.execute(select(user_sessions.c.id)).first() is None
        assert connection.execute(select(audit_logs.c.action).order_by(audit_logs.c.created_at.desc())).scalars().first() == "admin_password_recovered"


def test_migration_revision_fits_postgres_version_column():
    migration = import_module("backend.migrations.versions.0006_retention_protection_and_workers")
    assert len(migration.revision) <= 32


def test_validation_secret_rewrite_preserves_other_configuration():
    from scripts.rotate_validation_secrets import replace_env_values

    original = "POSTGRES_USER='vms'\nPOSTGRES_PASSWORD='old'\nVMS_OPERATOR_PASSWORD='old'\n"
    changed = replace_env_values(original, {
        "POSTGRES_PASSWORD": "new", "VMS_OPERATOR_PASSWORD": "other", "VMS_SESSION_SECRET": "session"
    })
    assert "POSTGRES_USER='vms'" in changed
    assert "POSTGRES_PASSWORD='new'" in changed
    assert "VMS_SESSION_SECRET='session'" in changed
    assert "PASSWORD='old'" not in changed
