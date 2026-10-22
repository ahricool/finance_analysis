from datetime import date, timedelta

import pytest
from sqlalchemy import select

from finance_analysis.database.models.stock_strategies import StockStrategyDay, StockStrategyRun
from finance_analysis.stock_strategies.engine import advance
from finance_analysis.stock_strategies.registry import STRATEGIES
from .helpers import inputs

SPEC = STRATEGIES[0]
DAY = date(2026, 10, 19)


def test_atomic_daily_transition_idempotency_and_success_not_downgraded(repository):
    repository.launch(DAY, "US", lambda: {"stocks": ["A.US"]})
    repository.initialize(SPEC, "US", DAY)
    snapshot = repository.settle(SPEC, "US", DAY, None, lambda state: advance(SPEC, state, inputs(), DAY))
    assert snapshot["nav"] == 1e6
    assert repository.settle(SPEC, "US", DAY, None, lambda _: pytest.fail("replayed")) is None
    repository.attempt(SPEC, "US", DAY, "failed", "late error")
    assert repository.latest(SPEC, "US")[1]["status"] == "success"
    assert len(repository.curve(SPEC, "US")) == 1
    assert repository.history(SPEC, "US", before=DAY) == []
    with pytest.raises(ValueError, match="跨过"):
        repository.settle(SPEC, "US", DAY + timedelta(days=2), None, lambda _: None)


def test_failed_insert_rolls_back_state_and_ledger(repository):
    repository.initialize(SPEC, "US", DAY)

    def calculate(state):
        updated, snapshot = advance(SPEC, state, inputs(), DAY)
        snapshot["nav"] = -1
        return updated, snapshot

    with pytest.raises(Exception):
        repository.settle(SPEC, "US", DAY, None, calculate)
    assert repository.state(SPEC, "US")["last_date"] is None
    assert repository.state(SPEC, "US")["payload"]["sessions"] == 0
    assert repository.history(SPEC, "US") == []


def test_global_launch_anchor_survives_freeze_failure_and_stays_read_only(repository):
    def fail():
        raise ValueError("universe unavailable")

    with pytest.raises(ValueError):
        repository.launch(DAY, "US", fail)
    start, universe = repository.launch(DAY + timedelta(days=2), "US", lambda: {"stocks": ["A.US"]})
    assert start == DAY
    assert universe["stocks"] == ["A.US"]
    repository.launch(DAY, "US", lambda: pytest.fail("must retain frozen membership"))
    with repository.db.get_session() as session:
        assert list(session.scalars(select(StockStrategyDay))) == []
        assert list(session.scalars(select(StockStrategyRun))) == []
