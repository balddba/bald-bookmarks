"""Alembic environment configuration for Bald Bookmarks."""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from bald_bookmarks.config import Settings, get_settings  # noqa: E402
from bald_bookmarks.db.models import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _alembic_settings() -> Settings:
    """Return settings injected by upgrade_schema, or load from the environment.

    Returns:
        Settings: Application settings for this Alembic run.
    """
    injected = config.attributes.get("settings")
    if injected is not None:
        return injected
    return get_settings()


def get_url() -> str:
    """Resolve the SQLAlchemy URL from application settings.

    Returns:
        str: SQLAlchemy URL for the configured driver.
    """
    return _alembic_settings().sqlalchemy_url


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""
    settings = _alembic_settings()
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=settings.normalized_driver == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode using application connection settings."""
    settings = _alembic_settings()
    if settings.normalized_driver == "oracle":
        connectable = create_engine(
            "oracle+oracledb://",
            connect_args=settings.oracle_connect_args(),
            poolclass=pool.NullPool,
        )
    else:
        connectable = create_engine(
            settings.sqlalchemy_url,
            poolclass=pool.NullPool,
        )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=settings.normalized_driver == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
