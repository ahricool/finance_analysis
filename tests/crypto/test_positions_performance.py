from datetime import timedelta
from decimal import Decimal as D

import pytest

from finance_analysis.crypto.models import StrategyState
from finance_analysis.crypto.performance import performance
from finance_analysis.crypto.position import change_position

from .helpers import START


def row(i, price, before, after, average=None):
    return dict(
        evaluated_at=START + timedelta(minutes=15 * i),
        price=D(price),
        position_before=D(before),
        position_after=D(after),
        position_delta=D(after) - D(before),
        average_entry_price=D(average) if average else None,
        action="BUY" if D(after) > D(before) else "EXIT" if D(after) < D(before) else "HOLD",
        reason="test",
    )


def test_partial_position_average_cost_and_compatibility():
    state = StrategyState()
    state = change_position(state, D(".5"), D(100), START)
    assert state.average_entry_price == 100 and state.position_state == "LONG"
    state = change_position(state, D(1), D(110), START + timedelta(minutes=15))
    assert state.average_entry_price == 105 and state.entry_time == START
    state = change_position(state, D(".5"), D(120), START + timedelta(minutes=30))
    assert state.average_entry_price == state.entry_price == 105
    state = change_position(state, D(0), D(90), START + timedelta(minutes=45))
    assert state.average_entry_price is None and state.entry_time is None and state.position_state == "FLAT"
    for bad in ("-.1", "1.1", "NaN"):
        with pytest.raises(ValueError):
            change_position(state, D(bad), D(100), START)
    assert StrategyState(position_state="LONG", entry_price=D(100)).position_pct == 1


def test_mark_to_market_drawdown_includes_open_periods():
    rows = [row(0, "100", "0", "1", "100"), row(1, "80", "1", "1", "100"), row(2, "110", "1", "0")]
    result = performance(rows, StrategyState())
    assert [x["equity"] for x in result["equity_curve"]] == [D(1), D(".8"), D("1.1")]
    assert result["max_drawdown"] == D(".2")
    assert result["cumulative_return"] == result["average_return"] == D(".1")
    assert (result["completed_cycles"], result["win_count"], result["loss_count"], result["execution_count"]) == (
        1,
        1,
        0,
        2,
    )
    assert result["win_rate"] == 1
    assert result["recent_trades"][0]["holding_seconds"] == 1800


def test_dynamic_position_equity_and_cycles():
    rows = [
        row(0, "100", "0", ".5", "100"),
        row(1, "110", ".5", "1", "105"),
        row(2, "99", "1", ".5", "105"),
        row(3, "110", ".5", "0"),
    ]
    result = performance(rows, StrategyState())
    assert result["equity_curve"][1]["equity"] == D("1.05")
    assert result["equity_curve"][2]["equity"] == D(".945")
    assert float(result["cumulative_return"]) == pytest.approx(-0.0025)
    assert result["completed_cycles"] == 1 and result["loss_count"] == 1
    assert result["recent_trades"][0]["average_entry_price"] == 105
    assert result["execution_count"] == 4


def test_open_cycles_not_wins_and_breakeven_in_denominator():
    rows = [
        row(0, "100", "0", "1", "100"),
        row(1, "110", "1", "0"),
        row(2, "100", "0", "1", "100"),
        row(3, "100", "1", "0"),
        row(4, "100", "0", ".5", "100"),
        row(5, "150", ".5", ".5", "100"),
    ]
    result = performance(rows, StrategyState(position_pct=D(".5"), average_entry_price=D(100)))
    assert result["completed_cycles"] == 2 and result["win_count"] == 1 and result["loss_count"] == 0
    assert result["win_rate"] == D(".5") and result["average_return"] == D(".05")
    assert result["cumulative_return"] == D(".375")
    assert result["best_trade"] == D(".1") and result["worst_trade"] == 0
    assert result["current_position"]["position_pct"] == D(".5")


def test_old_incomplete_and_missing_intervals_do_not_invent_executions_or_trades():
    old = {**row(0, "100", "0", "1", "100"), "position_before": None, "position_delta": None}
    rows = [
        old,
        row(1, "120", "1", "1", "100"),
        row(2, "110", "1", "0"),
        row(3, "100", "0", "1", "100"),
        row(4, "105", "1", "0"),
    ]
    result = performance(rows, StrategyState())
    assert result["performance_start_at"] == rows[1]["evaluated_at"]
    assert result["completed_cycles"] == 1 and result["execution_count"] == 3
    assert result["recent_trades"][0]["realized_return"] == D(".05")
    # A missing snapshot invalidates the preceding performance segment, not bridged with guesses.
    result = performance([rows[1], rows[3], rows[4]], StrategyState())
    assert result["performance_start_at"] == rows[3]["evaluated_at"]
    assert performance([old], StrategyState())["equity_curve"] == []
