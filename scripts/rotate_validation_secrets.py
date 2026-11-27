"""Rotate validation secrets while preserving encrypted camera sources and data."""

import os
import re
import secrets
import sys
import tempfile
from pathlib import Path

from psycopg import sql
from sqlalchemy import delete, select, update

from backend.app.core.config import load_settings
from backend.app.database.session import create_database
from backend.app.models.recordings import rtsp_cameras
from backend.app.models.users import user_sessions
from backend.app.services.rtsp import cipher
from backend.app.services.users import add_audit


SECRET_NAMES = (
    "POSTGRES_PASSWORD",
    "VMS_OPERATOR_PASSWORD",
    "VMS_SESSION_SECRET",
    "MEDIAMTX_API_PASSWORD",
    "MEDIAMTX_MEDIA_PASSWORD",
)


def replace_env_values(original, values):
    lines = original.splitlines()
    found = set()
    for index, line in enumerate(lines):
        name = line.split("=", 1)[0].strip()
        if name in values and re.fullmatch(r"[A-Z_]+", name):
            lines[index] = f"{name}='{values[name]}'"
            found.add(name)
    lines.extend(f"{name}='{values[name]}'" for name in values if name not in found)
    return "\n".join(lines) + "\n"


def atomic_write(path, content):
    descriptor, temporary = tempfile.mkstemp(prefix=".validation-env-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: rotate_validation_secrets.py /secure/validation.env | --check")
    if sys.argv[1] == "--check":
        settings = load_settings()
        engine = create_database(settings["database_url"])
        try:
            with engine.connect() as connection:
                rows = connection.execute(select(
                    rtsp_cameras.c.source_encrypted,
                    rtsp_cameras.c.preview_source_encrypted,
                )).mappings().all()
            decoder = cipher(settings["session_secret"])
            for row in rows:
                decoder.decrypt(row["source_encrypted"].encode())
                if row["preview_source_encrypted"]:
                    decoder.decrypt(row["preview_source_encrypted"].encode())
            print(f"Validation database reachable; {len(rows)} camera source(s) decrypt successfully.")
        finally:
            engine.dispose()
        return
    path = Path(sys.argv[1])
    original = path.read_text(encoding="utf-8")
    values = {name: secrets.token_urlsafe(48) for name in SECRET_NAMES}
    settings = load_settings()
    if not str(settings["database_url"]).startswith("postgresql"):
        raise SystemExit("Validation PostgreSQL connection required")

    engine = create_database(settings["database_url"])
    file_changed = False
    camera_count = 0
    try:
        with engine.begin() as connection:
            old_cipher = cipher(settings["session_secret"])
            new_cipher = cipher(values["VMS_SESSION_SECRET"])
            cameras = connection.execute(select(
                rtsp_cameras.c.id,
                rtsp_cameras.c.source_encrypted,
                rtsp_cameras.c.preview_source_encrypted,
            )).mappings().all()
            camera_count = len(cameras)
            for camera in cameras:
                source = old_cipher.decrypt(camera["source_encrypted"].encode())
                preview = camera["preview_source_encrypted"]
                changes = {"source_encrypted": new_cipher.encrypt(source).decode()}
                if preview:
                    changes["preview_source_encrypted"] = new_cipher.encrypt(
                        old_cipher.decrypt(preview.encode())
                    ).decode()
                connection.execute(update(rtsp_cameras).where(
                    rtsp_cameras.c.id == camera["id"]
                ).values(**changes))

            raw_connection = connection.connection.driver_connection
            with raw_connection.cursor() as cursor:
                cursor.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(os.environ["POSTGRES_USER"]),
                    sql.Literal(values["POSTGRES_PASSWORD"]),
                ))
            connection.execute(delete(user_sessions))
            add_audit(connection, "validation_secrets_rotated")
            atomic_write(path, replace_env_values(original, values))
            file_changed = True
    except Exception:
        if file_changed:
            atomic_write(path, original)
        raise SystemExit("Validation secret rotation failed; database transaction was rolled back") from None
    finally:
        engine.dispose()

    print(f"Validation secrets rotated; {camera_count} camera source(s) re-encrypted; sessions revoked.")


if __name__ == "__main__":
    main()
