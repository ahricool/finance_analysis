"""Exercise the real session-lock helper using deterministic PostgreSQL connection doubles."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from tests.test_task_advisory_lock import _SharedAdvisoryDatabase
from tests.trade_engine.test_trade_engine_service import NOW, _service, _portfolio, _position, ScriptedResolver
from finance_analysis.trade_engine.locking import market_decision_lock


def test_market_uid_lock_keys_and_no_idle_transaction():
    db = _SharedAdvisoryDatabase()
    with market_decision_lock(db, 1, "US") as first:
        assert first.acquired
        assert not first.connection.in_transaction
        with market_decision_lock(db, 1, "US") as same:
            assert not same.acquired
        with market_decision_lock(db, 1, "CN") as other_market:
            assert other_market.acquired
        with market_decision_lock(db, 2, "US") as other_user:
            assert other_user.acquired
    assert not db.held


def test_scheduled_and_manual_runs_share_lock(monkeypatch):
    db = _SharedAdvisoryDatabase()
    entered, finish = Event(), Event()
    resolver = ScriptedResolver()
    service = _service(_portfolio(_position()), resolver=resolver)
    service._lock_factory = lambda _db, uid, market: market_decision_lock(db, uid, market)
    original = resolver.decide
    from types import SimpleNamespace
    from fastapi import Response
    from finance_analysis.interfaces.api.v1.endpoints.trade_engine import run as manual_run
    from finance_analysis.tasks.celery.jobs.trade_engine import tasks

    service._active_uids = lambda market: [1]
    monkeypatch.setattr(tasks, "TradeEngineService", lambda: service)
    monkeypatch.setattr(tasks, "get_market_now", lambda market: NOW)
    monkeypatch.setattr(tasks, "is_market_open", lambda *args: True)
    monkeypatch.setattr(tasks, "in_evaluation_window", lambda *args: True)

    def decide(context):
        assert db.held
        assert all(not c.in_transaction for c in db.connections)
        entered.set()
        assert finish.wait(5)
        return original(context)

    resolver.decide = decide
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(tasks._run_market, "US")
        try:
            assert entered.wait(5)
            second = pool.submit(
                manual_run, SimpleNamespace(state=SimpleNamespace(uid=1)), Response(),
                market="US", service=service, _admin=True,
            ).result(timeout=3)
            assert second["status"] == "SKIPPED_LOCKED"
        finally:
            finish.set()
        assert first.result(timeout=5)["llm_reviews"] == 1
    assert len(resolver.calls) == 1
    assert not db.held


def test_lock_released_on_llm_exception():
    db = _SharedAdvisoryDatabase()
    service = _service(_portfolio(_position()))
    service._lock_factory = lambda _db, uid, market: market_decision_lock(db, uid, market)

    def fail(context):
        raise RuntimeError("LLM failed")

    service.decision_resolver.decide = fail
    with pytest.raises(RuntimeError, match="LLM failed"):
        service.evaluate_uid(1, market="US", now=NOW)
    assert not db.held
