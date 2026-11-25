"""Default-off shared settings and migration/ORM parity."""

import importlib.util
from contextlib import contextmanager
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from finance_analysis.database.models.minute_forecast import MinuteForecastPreference
from finance_analysis.database.repositories.minute_forecast import MinuteForecastPreferences


def test_empty_migration_and_repository_idempotent_shared_settings():
    engine = create_engine("sqlite://")
    spec = importlib.util.spec_from_file_location(
        "minute_optin_migration",
        Path(__file__).parents[2] / "alembic/versions/0100_minute_forecast_optin.py",
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    class DB:
        def get_session(self):
            return Session(engine)

        @contextmanager
        def session_scope(self):
            with Session(engine) as session, session.begin():
                yield session

    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
    assert inspect(engine).get_pk_constraint(MinuteForecastPreference.__tablename__)["constrained_columns"] == ["symbol"]
    repo = MinuteForecastPreferences(DB())
    assert not repo.enabled("AAPL.US")
    assert repo.enabled_symbols() == set()
    assert repo.set_enabled("AAPL.US", True)
    assert repo.set_enabled("AAPL.US", True)
    assert repo.set_enabled("600519.SH", True)
    assert MinuteForecastPreferences(DB()).enabled("AAPL.US")
    assert repo.enabled_symbols() == {"AAPL.US", "600519.SH"}
    assert not repo.set_enabled("AAPL.US", False)
    assert not repo.set_enabled("AAPL.US", False)
    assert repo.enabled_symbols() == {"600519.SH"}
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
    assert not inspect(engine).has_table(MinuteForecastPreference.__tablename__)
