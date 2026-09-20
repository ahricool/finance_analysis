from datetime import timedelta

import pytest

from finance_analysis.crypto.models import StrategyState
from finance_analysis.crypto.strategy import evaluate

from .helpers import candle


def test_snapshot_and_state_atomic_and_replay_does_not_duplicate(repository):
    rows = [candle(i) for i in range(15)]
    at = rows[-1].close_time
    calculate = lambda state: evaluate(rows, [], at, state)
    assert repository.evaluate_once("btc_breakout_v1", "BTCUSDT", at, calculate)["action"] == "WAIT"
    assert repository.evaluate_once("btc_breakout_v1", "BTCUSDT", at, lambda _: pytest.fail("recomputed")) is None
    assert len(repository.signals("btc_breakout_v1", "BTCUSDT")) == 1
    assert repository.state("btc_breakout_v1", "BTCUSDT").updated_at == at

    def broken(_):
        state, snapshot = evaluate([candle(15)], [], at + timedelta(minutes=15), StrategyState())
        snapshot["reason"] = None  # Fail at INSERT after applying state, not during validation.
        return state, snapshot

    with pytest.raises(Exception):
        repository.evaluate_once("btc_breakout_v1", "BTCUSDT", at + timedelta(minutes=15), broken)
    assert repository.state("btc_breakout_v1", "BTCUSDT").position_state == "FLAT"
    assert len(repository.signals("btc_breakout_v1", "BTCUSDT")) == 1


def test_rejects_skipped_time_and_rolls_back_state_update_failure(repository):
    from dataclasses import replace

    at = candle().close_time
    repository.evaluate_once("btc_breakout_v1", "BTCUSDT", at, lambda state: evaluate([candle()], [], at, state))
    with pytest.raises(ValueError, match="skip"):
        repository.evaluate_once(
            "btc_breakout_v1", "BTCUSDT", at + timedelta(minutes=30), lambda _: pytest.fail("must not calculate")
        )

    def broken(state):
        updated, snapshot = evaluate([candle(1)], [], at + timedelta(minutes=15), state)
        return replace(updated, updated_at=None), snapshot

    with pytest.raises(Exception):
        repository.evaluate_once("btc_breakout_v1", "BTCUSDT", at + timedelta(minutes=15), broken)
    assert (
        len(repository.signals("btc_breakout_v1", "BTCUSDT")) == 1
        and repository.state("btc_breakout_v1", "BTCUSDT").updated_at == at
    )
