"""Use only an explicitly isolated test database; never the application DATABASE_URL."""

import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select, text, inspect
from sqlalchemy.orm import sessionmaker

from finance_analysis.database.models.intraday_simulation import (
    IntradaySimulationTrade as Trade,
    IntradaySimulationEvent as Event,
)
from finance_analysis.database.repositories import intraday_simulation as store
from tests.intraday_options.test_simulation import NOW, quote, result


@pytest.fixture
def isolated_store(monkeypatch):
    url = os.getenv("INTRADAY_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Requires isolated INTRADAY_TEST_POSTGRES_URL")
    engine = create_engine(url)
    schema = "intraday_test_" + uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    factory = sessionmaker(scoped)

    @contextmanager
    def session_scope():
        with factory.begin() as session:
            yield session

    monkeypatch.setattr(store.DatabaseManager, "get_instance", lambda: SimpleNamespace(session_scope=session_scope))
    path = Path(__file__).parents[2] / "alembic/versions/0093_intraday_simulation.py"
    spec = importlib.util.spec_from_file_location("simulation_revision", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    try:
        with engine.begin() as conn:
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()
            assert len(inspect(conn).get_table_names(schema=schema)) == 3
        yield factory
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def test_concurrent_entry_exit_restart_atomic_evidence(isolated_store):
    def entry(_):
        return store.process("SPY.US", result(), quote(), NOW)

    with ThreadPoolExecutor(max_workers=8) as pool:
        states = list(pool.map(entry, range(16)))
    assert all(s["position"] for s in states)
    with isolated_store() as session:
        trades = list(session.scalars(select(Trade)))
        assert len(trades) == 1
        frozen = trades[0].payload["entry_evidence"]
        assert len([e for e in session.scalars(select(Event)) if e.payload["kind"] == "entry"]) == 1
    revised = result()
    revised["opportunities"]["branches"][0]["invalidation"] = 20
    later = NOW + timedelta(seconds=5)
    store.process("SPY.US", revised, quote(later), later)
    cutoff = NOW.replace(hour=19)
    with ThreadPoolExecutor(max_workers=8) as pool:
        states = list(pool.map(lambda _: store.process("SPY.US", None, None, cutoff), range(16)))
    assert all(not s["position"] for s in states)
    with isolated_store() as session:
        trades = list(session.scalars(select(Trade)))
        assert len(trades) == 1 and trades[0].status == "closed"
        assert trades[0].payload["entry_evidence"] == frozen
        assert trades[0].payload["estimated"]
        assert len([e for e in session.scalars(select(Event)) if e.payload["kind"] == "exit"]) == 1


def test_transaction_failure_rolls_back_state_and_events(isolated_store, monkeypatch):
    original = store.transition

    def broken(*args):
        state, events = original(*args)
        events.append(dict(kind="exit", trade_id="missing", trade={}))
        return state, events

    monkeypatch.setattr(store, "transition", broken)
    with pytest.raises(AttributeError):
        store.process("SPY.US", result(), quote(), NOW)
    with isolated_store() as session:
        assert not list(session.scalars(select(Trade)))
        assert not list(session.scalars(select(Event)))


def test_reconnect_cursor_recovers_previous_session_exit(isolated_store):
    store.process('SPY.US', result(), quote(), NOW)
    first = store.read(NOW.date())
    cursor = max(e['id'] for e in first['events'])
    cutoff = NOW.replace(hour=19)
    store.process('SPY.US', None, None, cutoff)
    tomorrow = (NOW + timedelta(days=1)).date()
    assert not store.read(tomorrow)['events']
    replay = store.read(tomorrow, cursor)
    assert [e['kind'] for e in replay['events']] == ['exit']
    assert len({e['id'] for e in replay['events']}) == len(replay['events'])


def test_continuation_concurrent_restart_preserves_frozen_method_and_structure(isolated_store):
    from tests.intraday_options.test_continuation import path
    from tests.intraday_options.test_scoring import score

    bars = path()
    now = bars[-1].bar_time + timedelta(minutes=1, seconds=5)
    r = score(bars)
    with ThreadPoolExecutor(max_workers=4) as pool:
        states = list(pool.map(lambda _: store.process("SPY.US", r, quote(now, 104), now), range(8)))
    assert all(s["position"]["kind"] == "trend_continuation" for s in states)
    with isolated_store() as session:
        trades = list(session.scalars(select(Trade)))
        assert len(trades) == 1
        frozen = trades[0].payload["entry_evidence"]
        assert frozen["confirmation_method"] == "strong_break"
        assert frozen["structure_high"] and frozen["atr_samples"] >= 15
    b = r["opportunities"]["branches"][0]
    b.update(atr=10, structure_high=200)
    store.process("SPY.US", r, quote(now + timedelta(seconds=5), 104), now + timedelta(seconds=5))
    store.process("SPY.US", r, quote(now + timedelta(seconds=10), 103), now + timedelta(seconds=10))
    with isolated_store() as session:
        trades = list(session.scalars(select(Trade)))
        assert len(trades) == 1 and trades[0].status == "closed"
        assert trades[0].payload["entry_evidence"] == frozen
        events = list(session.scalars(select(Event)))
        assert sum(e.payload["kind"] == "entry" for e in events) == 1
        assert sum(e.payload["kind"] == "exit" for e in events) == 1
