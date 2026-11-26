from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url

from backend.app.models.recordings import metadata
from backend.app.models import users as user_models


def create_database(url):
    options = {"pool_pre_ping": True}
    if make_url(url).get_backend_name() == "sqlite":
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, **options)
    if engine.dialect.name == "sqlite":
        def configure_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
        event.listen(engine, "connect", configure_sqlite)
    metadata.create_all(engine)
    return engine
