from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from finance_analysis.crypto.models import StrategyState
from finance_analysis.crypto.strategy import evaluate
from .helpers import START, candle


def test_upsert_idempotent_and_partial_bars_never_persist(repository):
    row = candle()
    now = START + timedelta(minutes=3)
    repository.upsert_klines([row, row, candle(1, closed=False)])
    assert len(repository.klines(as_of=now)) == 1
    repository.upsert_klines([replace(row, close=Decimal("100.123456789012"))])
    actual = repository.klines(as_of=now)
    assert len(actual) == 1 and actual[0].close == Decimal("100.123456789012")
    assert actual[0].volume == row.volume
    assert actual[0].open_time == START


def test_snapshot_and_state_atomic_and_replay_does_not_duplicate(repository):
    rows = [candle(i) for i in range(15)]
    at = rows[-1].close_time
    calculate = lambda state: evaluate(rows, at, state)
    assert repository.evaluate_once(at, calculate)["action"] == "WAIT"
    assert repository.evaluate_once(at, lambda _: pytest.fail("recomputed")) is None
    assert len(repository.signals()) == 1
    assert repository.state().updated_at == at

    def broken(_):
        return StrategyState(position_state="LONG", updated_at=at + timedelta(minutes=15)), {"symbol": "BTCUSDT"}

    with pytest.raises(Exception):
        repository.evaluate_once(at + timedelta(minutes=15), broken)
    assert repository.state().position_state == "FLAT"
    assert len(repository.signals()) == 1
