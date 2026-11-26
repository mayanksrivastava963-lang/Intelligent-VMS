"""Alembic configuration for the shared VMS metadata."""

from alembic import context
from sqlalchemy import create_engine, pool

from backend.app.core.config import load_settings
from backend.app.models.recordings import metadata
from backend.app.models import users  # Register auth tables with metadata.


target_metadata = metadata


def run_migrations_offline():
    context.configure(url=str(load_settings()["database_url"]), target_metadata=target_metadata,
                      literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = create_engine(load_settings()["database_url"], poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
