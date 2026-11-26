from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url

from backend.app.models.recordings import metadata
from backend.app.models import users as user_models


def create_database(url, pool_size=5, max_overflow=5, pool_recycle=1800):
    options = {"pool_pre_ping": True}
    if make_url(url).get_backend_name() == "sqlite":
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        options.update(pool_size=pool_size, max_overflow=max_overflow,
                       pool_recycle=pool_recycle, pool_timeout=15)
    engine = create_engine(url, **options)
    if engine.dialect.name == "sqlite":
        def configure_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
        event.listen(engine, "connect", configure_sqlite)
    metadata.create_all(engine)
    # Keep existing local databases usable until the Alembic baseline is applied.
    columns = {column["name"] for column in inspect(engine).get_columns("rtsp_cameras")}
    with engine.begin() as connection:
        if "health_status" not in columns:
            connection.execute(text("ALTER TABLE rtsp_cameras ADD COLUMN health_status VARCHAR(20) DEFAULT 'stopped' NOT NULL"))
        if "last_frame_at" not in columns:
            connection.execute(text("ALTER TABLE rtsp_cameras ADD COLUMN last_frame_at FLOAT"))
        if "preview_source_encrypted" not in columns:
            connection.execute(text("ALTER TABLE rtsp_cameras ADD COLUMN preview_source_encrypted VARCHAR(4096)"))
    return engine
