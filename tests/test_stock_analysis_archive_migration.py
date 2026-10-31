"""Delete old stock archives without removing unrelated market or audit data."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from finance_analysis.database.base import Base
import finance_analysis.database.models  # noqa: F401

ARCHIVES = ("analysis_history", "fundamental_snapshot")
SURVIVORS = ("task", "notification", "llm_usage", "news_intel", "stock_daily")
PRESENT_CASES = (ARCHIVES, ARCHIVES[:1], ARCHIVES[1:], ())


def _exercise(connection, monkeypatch, present):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0084_drop_stock_analysis_archive.py"
    spec = importlib.util.spec_from_file_location("drop_stock_archive", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    metadata = sa.MetaData()
    for name in (*present, *SURVIVORS):
        table = sa.Table(name, metadata, sa.Column("id", sa.Integer, primary_key=True), sa.Column("payload", sa.Text))
        table.create(connection)
        connection.execute(table.insert().values(id=1, payload="existing data"))
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
    migration.upgrade()
    migration.upgrade()
    tables = set(sa.inspect(connection).get_table_names())
    assert not tables.intersection(ARCHIVES)
    for name in SURVIVORS:
        assert connection.scalar(sa.select(metadata.tables[name].c.payload)) == "existing data"
    with pytest.raises(RuntimeError, match="irreversible"):
        migration.downgrade()


def test_fresh_database_metadata_excludes_deleted_archives():
    assert not set(Base.metadata.tables).intersection(ARCHIVES)
    assert set(SURVIVORS).issubset(Base.metadata.tables)


@pytest.mark.parametrize("present", PRESENT_CASES)
def test_drop_archive_sqlite(monkeypatch, present):
    with sa.create_engine("sqlite://").begin() as connection:
        _exercise(connection, monkeypatch, present)


@pytest.mark.parametrize("present", PRESENT_CASES)
def test_drop_archive_postgresql(monkeypatch, present):
    url = os.getenv("STOCK_RETIREMENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("STOCK_RETIREMENT_TEST_DATABASE_URL must point to an isolated test database")
    engine = sa.create_engine(url)
    schema = "stock_archive_" + uuid4().hex
    try:
        with engine.begin() as connection:
            connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
            _exercise(connection, monkeypatch, present)
            connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        engine.dispose()
