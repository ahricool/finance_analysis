"""Verify table removal and schema-only rollback without touching intraday records."""

import importlib.util

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from finance_analysis.core.paths import PROJECT_ROOT
from finance_analysis.database import Base


def test_drop_signal_preserves_calendar_and_restores_schema():
    spec = importlib.util.spec_from_file_location(
        "drop_signal_migration", PROJECT_ROOT / "alembic/versions/0041_drop_signal.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert "signal" not in Base.metadata.tables
    with sa.create_engine("sqlite://").begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        connection.execute(sa.text("CREATE TABLE calendar (id INTEGER PRIMARY KEY, type TEXT)"))
        connection.execute(sa.text("INSERT INTO calendar VALUES (1, 'us_intraday_signal')"))
        migration.downgrade()
        assert len(sa.inspect(connection).get_indexes("signal")) == 4
        assert len(sa.inspect(connection).get_check_constraints("signal")) == 2
        migration.upgrade()
        migration.upgrade()  # Also supports databases bootstrapped from current metadata.
        assert "signal" not in sa.inspect(connection).get_table_names()
        assert connection.execute(sa.text("SELECT type FROM calendar")).scalar_one() == "us_intraday_signal"
        migration.downgrade()
        assert "direction" in {column["name"] for column in sa.inspect(connection).get_columns("signal")}
