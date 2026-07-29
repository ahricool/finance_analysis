# -*- coding: utf-8 -*-
"""Alembic migration environment (PostgreSQL, SQLAlchemy 2.x)."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect, pool
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

import finance_analysis.database.models  # noqa: F401  # register ORM models on Base.metadata
from finance_analysis.config import load_env
from finance_analysis.database.base import Base
from finance_analysis.database.config import get_database_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

load_env()
target_metadata = Base.metadata


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    """Let the SQLite migration test database represent PostgreSQL JSONB as JSON."""
    return "JSON"


def _bootstrap_empty_database(connection) -> bool:
    """Create current metadata and stamp head when Alembic is run on a truly empty database.

    The collapsed baseline intentionally loads current ORM metadata. Running every
    historical delta after that would recreate or alter already-final tables, so a
    fresh database is equivalent to creating current metadata and stamping the
    single migration head. Existing databases always follow the normal revision
    chain and therefore still execute data migrations such as portfolio seeding.
    """
    if inspect(connection).get_table_names():
        return False
    target_metadata.create_all(bind=connection)
    version_table = Table(
        "alembic_version",
        MetaData(),
        Column("version_num", String(32), primary_key=True),
    )
    version_table.create(bind=connection)
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError("Alembic migration head is unavailable")
    connection.execute(version_table.insert().values(version_num=head))
    return True


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

    with connectable.begin() as connection:
        if _bootstrap_empty_database(connection):
            return
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
