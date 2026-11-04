"""Ten-day rollout preserves official history and preview rows for older periods."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_ten_day_constraint_upgrade_preserves_history_and_downgrade_removes_only_ten(backend):
    path = Path(__file__).parents[1] / "alembic/versions/0090_trend_ten_day.py"
    spec = importlib.util.spec_from_file_location("ten_day_revision", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    url = os.getenv("PREVIEW_TEST_POSTGRES_URL") if backend == "postgres" else "sqlite://"
    if not url:
        pytest.skip("Requires an isolated PREVIEW_TEST_POSTGRES_URL")
    engine = create_engine(url)
    with engine.begin() as connection:
        schema = "trend_period_test_" + uuid4().hex
        if backend == "postgres":
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        for table, name, column, periods in migration.CONSTRAINTS:
            allowed = ", ".join(str(period) for period in periods)
            connection.execute(text(
                f"CREATE TABLE {table} ({column} INTEGER PRIMARY KEY, "
                f"CONSTRAINT {name} CHECK ({column} IN ({allowed})))"
            ))
            for period in (20, 60):
                connection.execute(text(f"INSERT INTO {table} VALUES (:period)"), {"period": period})
        connection.execute(text("CREATE TABLE research_preview_item (variant INTEGER)"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        for table, name, column, _ in migration.CONSTRAINTS:
            assert connection.execute(text(f"SELECT {column} FROM {table} ORDER BY {column}")).scalars().all() == [20, 60]
            connection.execute(text(f"INSERT INTO {table} VALUES (10)"))
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(text(f"INSERT INTO {table} VALUES (30)"))
            assert "10" in next(c["sqltext"] for c in inspect(connection).get_check_constraints(table) if c["name"] == name)
        connection.execute(text("INSERT INTO research_preview_item VALUES (10), (60)"))
        migration.downgrade()
        for table, _, column, _ in migration.CONSTRAINTS:
            assert connection.execute(text(f"SELECT {column} FROM {table} ORDER BY {column}")).scalars().all() == [20, 60]
        assert connection.execute(text("SELECT variant FROM research_preview_item")).scalars().all() == [60]
        migration.upgrade()
        if backend == "postgres":
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()
