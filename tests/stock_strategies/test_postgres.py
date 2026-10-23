"""Opt-in isolated PostgreSQL tests: JSONB, row serialization and advisory mutex."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from uuid import uuid4
from datetime import date

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from finance_analysis.database.models.stock_strategies import (
    StockStrategyDay,
    StockStrategyLaunch,
    StockStrategyRun,
    StockStrategyState,
)
from finance_analysis.database.repositories.stock_strategies import StockStrategyRepository
from finance_analysis.stock_strategies.engine import advance
from finance_analysis.stock_strategies.registry import STRATEGIES
from finance_analysis.tasks.advisory_lock import PostgreSQLAdvisoryLock, TaskAdvisoryLockId
from .helpers import inputs


@pytest.fixture
def postgres():
    url = os.getenv("STOCK_STRATEGY_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Requires an explicitly isolated STOCK_STRATEGY_TEST_POSTGRES_URL")
    engine = create_engine(url)
    schema = "strategy_test_" + uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    for model in (StockStrategyLaunch, StockStrategyState, StockStrategyDay, StockStrategyRun):
        model.__table__.create(scoped)

    class DB:
        def connect(self):
            return scoped.connect()

        def get_session(self):
            return Session(scoped)

        @contextmanager
        def session_scope(self):
            with Session(scoped) as session, session.begin():
                yield session

    try:
        yield StockStrategyRepository(DB())
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def test_postgres_two_workers_serialize_one_daily_fill(postgres):
    spec, day = STRATEGIES[0], date(2026, 10, 19)
    postgres.initialize(spec, "US", day)
    entered, release = Event(), Event()
    calls = []

    def calculate(state):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return advance(spec, state, inputs(), day)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(postgres.settle, spec, "US", day, None, calculate)
        assert entered.wait(5)
        second = pool.submit(postgres.settle, spec, "US", day, None, calculate)
        release.set()
        assert first.result(timeout=10)["nav"] == 1e6
        assert second.result(timeout=10) is None
    assert calls == [1]
    assert len(postgres.curve(spec, "US")) == 1
    assert postgres.latest(spec, "US")[1]["status"] == "success"


def test_postgres_market_mutex_is_nonblocking_and_released(postgres):
    with PostgreSQLAdvisoryLock(TaskAdvisoryLockId.STOCK_STRATEGIES_US, db_manager=postgres.db) as first:
        assert first.acquired
        with PostgreSQLAdvisoryLock(TaskAdvisoryLockId.STOCK_STRATEGIES_US, db_manager=postgres.db) as second:
            assert not second.acquired
        with PostgreSQLAdvisoryLock(TaskAdvisoryLockId.STOCK_STRATEGIES_CN, db_manager=postgres.db) as other:
            assert other.acquired
    with PostgreSQLAdvisoryLock(TaskAdvisoryLockId.STOCK_STRATEGIES_US, db_manager=postgres.db) as third:
        assert third.acquired


def test_postgres_migration_creates_jsonb_and_downgrades(postgres):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import inspect
    from sqlalchemy.dialects.postgresql import JSONB
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parents[2] / "alembic/versions/0076_stock_strategies.py"
    spec = importlib.util.spec_from_file_location("strategy_pg_revision", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with postgres.db.connect() as connection, connection.begin():
        schema = connection.get_execution_options()["schema_translate_map"][None]
        for model in (StockStrategyRun, StockStrategyDay, StockStrategyState, StockStrategyLaunch):
            model.__table__.drop(connection)
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert len(inspect(connection).get_table_names(schema=schema)) == 4
        columns = {c["name"]: c for c in inspect(connection).get_columns("stock_strategy_day", schema=schema)}
        assert isinstance(columns["payload"]["type"], JSONB)
        migration.downgrade()
        assert inspect(connection).get_table_names(schema=schema) == []


@pytest.mark.parametrize("allow_entry", [False, True])
def test_postgres_two_days_with_real_pandas_indicator_scalars(postgres, allow_entry):
    """Production failed on day two even while flat; handwritten floats hid it."""
    from types import SimpleNamespace
    from finance_analysis.stock_strategies.inputs import InputLoader
    from .test_inputs import Repository, universe

    spec, first, second = STRATEGIES[0], date(2026, 10, 19), date(2026, 10, 20)
    loader = InputLoader(repository=Repository(), resolver=SimpleNamespace())
    postgres.initialize(spec, "US", first)
    for day, previous in ((first, None), (second, first)):
        data = loader.load("US", day, universe())
        if not allow_entry:
            for features in data.features.values():
                features["ma20"] = features["close"] + 1
        result = postgres.settle(spec, "US", day, previous, lambda state: advance(spec, state, data, first))
        assert result["nav"] > 0
    state = postgres.state(spec, "US")
    assert state["last_date"] == second
    assert bool(state["payload"]["positions"]) == allow_entry
    assert len(postgres.curve(spec, "US")) == 2
    assert postgres.latest(spec, "US")[1]["status"] == "success"
    assert postgres.settle(spec, "US", second, first, lambda _: pytest.fail("duplicate settlement")) is None
