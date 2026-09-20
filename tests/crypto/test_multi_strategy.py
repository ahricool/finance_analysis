import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError

from finance_analysis.crypto.performance import annualized_return, performance
from finance_analysis.crypto.position import change_position
from finance_analysis.crypto.registry import StrategyDefinition
from finance_analysis.crypto.service import CryptoService
from finance_analysis.crypto.strategy import evaluate
from finance_analysis.database.models.crypto import CryptoStrategySnapshot

from .helpers import START, candle
from .test_positions_performance import row

KEYS = ("btc_breakout_v1", "btc_test_strategy_v1", "btc_cold_v1")
SYMBOL = "BTCUSDT"


def test_different_catchup_and_cold_start_share_market_window(repository):
    at = START + timedelta(hours=60)
    q = [candle(i) for i in range(140, 243)]
    h = [candle(i, interval="1h") for i in range(60)]
    for key, minutes in zip(KEYS, (0, 30)):
        time = at + timedelta(minutes=minutes)
        repository.evaluate_once(key, SYMBOL, time, lambda state: evaluate(q, h, time, state))
    definitions = tuple(StrategyDefinition(key, key, evaluate) for key in KEYS)
    client = AsyncMock()
    client.server_time.return_value = at + timedelta(minutes=46)
    client.klines.side_effect = lambda **kw: q if kw["interval"] == "15m" else h
    result = asyncio.run(CryptoService(repository, binance=client, definitions=definitions).run())
    assert [item["evaluations"] for item in result["strategies"]] == [3, 1, 1]
    assert client.klines.await_count == 2 and client.server_time.await_count == 1
    assert [len(repository.signals(key, SYMBOL)) for key in KEYS] == [4, 2, 1]
    for key in KEYS:
        assert repository.state(key, SYMBOL).strategy_key == key
        assert repository.latest_snapshot_time(key, SYMBOL) == at + timedelta(minutes=45)


def test_composite_uniqueness_atomic_rollback_and_independent_performance(repository):
    definitions = tuple(StrategyDefinition(key, key, evaluate) for key in KEYS[:2])
    service = CryptoService(repository, definitions=definitions)
    for key, exit_price in zip(KEYS, (D(120), D(90))):
        for index, target in enumerate((D(1), D(0))):
            bar = candle(index)
            price = D(100) if index == 0 else exit_price

            def calculate(state):
                _, snapshot = evaluate([bar], [], bar.close_time, state)
                updated = change_position(state, target, price, bar.close_time)
                snapshot.update(
                    price=price,
                    action="BUY" if target else "EXIT",
                    position_before=state.position_pct,
                    position_after=target,
                    position_delta=target - state.position_pct,
                    average_entry_price=updated.average_entry_price,
                    position_state=updated.position_state,
                )
                return updated, snapshot

            repository.evaluate_once(key, SYMBOL, bar.close_time, calculate)
    assert service.get_performance(KEYS[0], SYMBOL)["total_return"] == D(".2")
    assert service.get_performance(KEYS[1], SYMBOL)["total_return"] == D("-.1")
    assert len(repository.signals(KEYS[0], SYMBOL)) == len(repository.signals(KEYS[1], SYMBOL)) == 2
    duplicate = dict(repository.signals(KEYS[0], SYMBOL)[0])
    duplicate.pop("id")
    with pytest.raises(IntegrityError), repository.db.session_scope() as session:
        session.add(CryptoStrategySnapshot(**duplicate))
    before = repository.state(KEYS[0], SYMBOL)

    def broken(state):
        updated, snapshot = evaluate([candle(2)], [], candle(2).close_time, state)
        snapshot["reason"] = None
        return replace(updated, highest_price_since_entry=D(999)), snapshot

    with pytest.raises(IntegrityError):
        repository.evaluate_once(KEYS[0], SYMBOL, candle(2).close_time, broken)
    assert repository.state(KEYS[0], SYMBOL) == before
    assert repository.latest_snapshot_time(KEYS[1], SYMBOL) == candle(1).close_time


def test_cagr_calendar_duration_peak_drawdown_and_curve_bound():
    assert annualized_return(D("1.21"), D(365)) == D(".21")
    assert annualized_return(D("1.21"), D(0)) is None
    assert annualized_return(D("1.01"), D(".01")) > D("1e100")  # no short-duration clamp
    from finance_analysis.crypto.models import StrategyState

    rows = [row(i, price, "0" if i == 0 else "1", "1", "100") for i, price in enumerate(("100", "120", "90", "130"))]
    result = performance(rows, StrategyState())
    assert result["max_drawdown"] == D("-.25")
    assert result["running_days"] == D(45) / 1440
    assert result["closed_trades"] == 0
    many = [row(i, "100", "0", "0") for i in range(2001)]
    result = performance(many, StrategyState())
    assert result["equity_points_total"] == 2001 and len(result["equity_curve"]) == 1000
    assert result["equity_curve"][0]["evaluated_at"] == many[0]["evaluated_at"]
    assert result["equity_curve"][-1]["evaluated_at"] == many[-1]["evaluated_at"]


def test_one_year_cagr_uses_snapshot_dates():
    from finance_analysis.crypto.models import StrategyState

    rows = [row(i, "121" if i == 365 * 96 else "100", "0" if i == 0 else "1", "1", "100") for i in range(365 * 96 + 1)]
    result = performance(rows, StrategyState(position_pct=D(1), average_entry_price=D(100)))
    assert result["running_days"] == 365
    assert result["total_return"] == result["annualized_return"] == D(".21")


def test_failure_does_not_block_other_strategies_and_disabled_is_not_evaluated(repository):
    at = START + timedelta(hours=60)
    client = AsyncMock()
    client.server_time.return_value = at
    client.klines.side_effect = lambda **kw: (
        [candle(i) for i in range(140, 240)]
        if kw["interval"] == "15m"
        else [candle(i, interval="1h") for i in range(60)]
    )

    def fail(*args):
        raise ValueError("test failure")

    definitions = (
        StrategyDefinition(KEYS[0], "broken", fail),
        StrategyDefinition(KEYS[1], "working", evaluate),
        StrategyDefinition(KEYS[2], "disabled", fail, enabled=False),
    )
    with pytest.raises(ValueError, match="test failure"):
        asyncio.run(CryptoService(repository, binance=client, definitions=definitions).run())
    assert repository.latest_snapshot_time(KEYS[0], SYMBOL) is None
    assert repository.latest_snapshot_time(KEYS[1], SYMBOL) == at
    assert repository.latest_snapshot_time(KEYS[2], SYMBOL) is None
    assert client.klines.await_count == 2
