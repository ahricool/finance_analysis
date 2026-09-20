from datetime import timedelta

import pytest

from finance_analysis.crypto.models import StrategyState
from finance_analysis.crypto.strategy import evaluate

from .helpers import candle


def test_snapshot_and_state_atomic_and_replay_does_not_duplicate(repository):
    rows = [candle(i) for i in range(15)]
    at = rows[-1].close_time
    calculate = lambda state: evaluate(rows, [], at, state)
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
