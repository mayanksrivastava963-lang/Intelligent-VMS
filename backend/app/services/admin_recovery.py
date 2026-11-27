"""Offline administrator password diagnosis and recovery.

Run in the recording-api container with an interactive terminal. For private
automation, passwords can also be read from stdin. They are never accepted as
command-line arguments. A short password override is limited to the local
validation administrator and validation database.
"""

import argparse
import getpass
import sys
import time

from sqlalchemy import delete, func, select, text, update

from backend.app.core.config import load_settings
from backend.app.core.security import hash_password, verify_password
from backend.app.database.session import create_database
from backend.app.models.users import audit_logs, user_sessions, users
from backend.app.services.users import add_audit, get_user_by_username


def password_allowed(password, database_name, username, allow_short_validation_password=False):
    if 12 <= len(password) <= 256:
        return True
    return (
        allow_short_validation_password
        and database_name.startswith("intelligent_vms_validation_")
        and username == "validation-admin"
        and 1 <= len(password) <= 256
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "verify", "reset"))
    parser.add_argument("--password-stdin", action="store_true", help="Read password lines from stdin without printing them")
    parser.add_argument("--allow-short-validation-password", action="store_true", help="Allow a short password only in the local validation database")
    args = parser.parse_args()

    settings = load_settings()
    engine = create_database(settings["database_url"])
    try:
        with engine.connect() as connection:
            if engine.dialect.name == "postgresql":
                database = connection.execute(text("SELECT current_database(), inet_server_addr(), inet_server_port()" )).one()
                print(f"Database: {database[0]} at {database[1]}:{database[2]}")
        username = settings["operator_username"]
        user = get_user_by_username(engine, username)
        if user is None:
            raise SystemExit("Configured administrator username is absent from the application database")
        if user["role_id"] != "super_administrator":
            raise SystemExit("Configured account is not a super administrator")

        if args.action == "check":
            encoded = user["password_hash"]
            with engine.connect() as connection:
                recovery_count = connection.execute(select(func.count()).select_from(audit_logs).where(
                    audit_logs.c.action == "admin_password_recovered",
                    audit_logs.c.target_user_id == user["id"],
                )).scalar_one()
            print(f"Account: {user['username']}; active: {user['is_active']}; role: {user['role_id']}")
            print(f"Hash format: {'argon2' if encoded.startswith('$argon2') else 'other'}")
            print(f"Bootstrap environment password matches stored hash: {verify_password(settings['operator_password'], encoded)}")
            print(f"Recorded offline recovery events: {recovery_count}")
            return

        if args.action == "verify":
            supplied = sys.stdin.readline().rstrip("\r\n") if args.password_stdin else getpass.getpass("Administrator password: ")
            print(f"Password valid: {user['is_active'] and verify_password(supplied, user['password_hash'])}")
            return

        if not user["is_active"]:
            raise SystemExit("Administrator account is inactive; recovery refused")
        if args.password_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
            confirmation = sys.stdin.readline().rstrip("\r\n")
        else:
            password = getpass.getpass("New administrator password: ")
            confirmation = getpass.getpass("Confirm new administrator password: ")
        if password != confirmation:
            raise SystemExit("Passwords did not match")
        database_name = engine.url.database or ""
        if not password_allowed(password, database_name, user["username"], args.allow_short_validation_password):
            raise SystemExit("Password must contain 12 to 256 characters")
        password_hash = hash_password(password)
        with engine.begin() as connection:
            connection.execute(update(users).where(users.c.id == user["id"]).values(
                password_hash=password_hash, updated_at=time.time()
            ))
            connection.execute(delete(user_sessions).where(user_sessions.c.user_id == user["id"]))
            add_audit(connection, "admin_password_recovered", target_user_id=user["id"])
        print("Administrator password updated; existing sessions revoked.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
