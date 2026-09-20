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


def test_full_position_cost_and_compatibility():
    state = change_position(StrategyState(), D(1), D(100), START)
    assert state.average_entry_price == state.entry_price == 100
    held = change_position(state, D(1), D(110), START + timedelta(minutes=15))
    assert held.average_entry_price == 100 and held.entry_time == START
    flat = change_position(held, D(0), D(90), START + timedelta(minutes=30))
    assert flat.average_entry_price is None and flat.entry_price is None
    assert flat.entry_time is None and flat.position_state == "FLAT"
    for bad in ("-.1", "1.1", "NaN"):
        with pytest.raises(ValueError):
            change_position(flat, D(bad), D(100), START)
    assert StrategyState(position_state="LONG", entry_price=D(100)).position_pct == 1


def test_partial_entry_and_reduction_allowed_but_addition_explicitly_rejected():
    state = change_position(StrategyState(), D(".5"), D(100), START)
    assert state.position_pct == D(".5") and state.average_entry_price == 100
    with pytest.raises(ValueError, match="Partial position cost accounting is not implemented"):
        change_position(state, D(1), D(110), START + timedelta(minutes=15))
    assert state.position_pct == D(".5") and state.average_entry_price == 100
    reduced = change_position(state, D(".25"), D(120), START + timedelta(minutes=30))
    assert reduced.average_entry_price == reduced.entry_price == 100 and reduced.entry_time == START
    flat = change_position(reduced, D(0), D(90), START + timedelta(minutes=45))
    assert flat.average_entry_price is None and flat.position_pct == 0


def test_mark_to_market_drawdown_includes_open_periods():
    rows = [row(0, "100", "0", "1", "100"), row(1, "80", "1", "1", "100"), row(2, "110", "1", "0")]
    result = performance(rows, StrategyState())
    assert [x["equity"] for x in result["equity_curve"]] == [D(1), D(".8"), D("1.1")]
    assert result["max_drawdown"] == D("-.2")
    assert result["total_return"] == result["average_trade_return"] == D(".1")
    assert (result["closed_trades"], result["wins"], result["losses"], result["execution_count"]) == (
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
        row(1, "110", ".5", ".5", "100"),
        row(2, "88", ".5", ".25", "100"),
        row(3, "105.6", ".25", "0"),
    ]
    result = performance(rows, StrategyState())
    assert result["equity_curve"][1]["equity"] == D("1.05")
    assert result["equity_curve"][2]["equity"] == D(".945")
    assert float(result["total_return"]) == pytest.approx(-0.00775)
    assert result["closed_trades"] == 1 and result["losses"] == 1
    assert result["recent_trades"][0]["average_entry_price"] == 100
    assert result["execution_count"] == 3


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
    assert result["closed_trades"] == 2 and result["wins"] == 1 and result["losses"] == 0
    assert result["breakeven"] == 1
    assert result["win_rate"] == D(".5") and result["average_trade_return"] == D(".05")
    assert result["total_return"] == D(".375")
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
    assert result["closed_trades"] == 1 and result["execution_count"] == 3
    assert result["recent_trades"][0]["realized_return"] == D(".05")
    # A missing snapshot invalidates the preceding performance segment, not bridged with guesses.
    result = performance([rows[1], rows[3], rows[4]], StrategyState())
    assert result["performance_start_at"] == rows[3]["evaluated_at"]
    assert performance([old], StrategyState())["equity_curve"] == []
