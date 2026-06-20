# -*- coding: utf-8 -*-
"""Alembic migration environment (PostgreSQL, SQLAlchemy 2.x)."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from src.config import load_env
from src.db.config import get_database_config
from src.db.base import Base
import src.models  # noqa: F401  # register ORM models on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

load_env()
target_metadata = Base.metadata


def get_database_url() -> str:
    """Resolve DB URL the same way as the application runtime."""
    return get_database_config().get_db_url()


def run_migrations_offline() -> None:
    """Generate SQL without a live DB connection (``alembic upgrade --sql``)."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in-process against a live engine/connection."""
    connectable = context.config.attributes.get("connection")
    if connectable is None:
        connectable = create_engine(get_database_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
