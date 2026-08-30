from __future__ import annotations

from datetime import date, timedelta

import pytest

from finance_analysis.stocks.reference_data.stock_index import (
    CSI300_STOCK_INDEX,
    CSI500_STOCK_INDEX,
    SP500_STOCK_INDEX,
)
from finance_analysis.trend_following.config import DEFAULT_CONFIG
from finance_analysis.trend_following.features import calculate_atr, calculate_features, weighted_log_regression
from finance_analysis.trend_following.models import DailyBar
from finance_analysis.trend_following.ranking import rank_candidates
from finance_analysis.trend_following.regime import calculate_market_regime
from finance_analysis.trend_following.risk import initial_risk_levels, next_add_price, trailing_stop
from finance_analysis.trend_following.state import transition_state
from finance_analysis.trend_following.universe import get_universe

TRADE_DATE = date(2026, 8, 28)


def bars(*, count: int = 80, start: float = 100.0, step: float = 1.0, final: float | None = None):
    result = []
    for index in range(count):
        close = start + index * step
        if final is not None and index == count - 1:
            close = final
        result.append(DailyBar(
            TRADE_DATE - timedelta(days=count - index - 1), close - 0.5, close + 1.0, close - 1.0,
            close, 1_000 + index * 10,
        ))
    return result


def test_fixed_universes_are_independent_and_complete():
    cn_codes = {member.code for member in get_universe("CN")}
    us_codes = {member.code for member in get_universe("US")}
    assert len(CSI500_STOCK_INDEX) == 500
    assert cn_codes == set(CSI300_STOCK_INDEX) | set(CSI500_STOCK_INDEX)
    assert us_codes == {f"{code}.US" for code in SP500_STOCK_INDEX}


def test_weighted_slope_r_squared_returns_drawdown_and_atr():
    series = bars(step=1.0)
    slope, r_squared = weighted_log_regression([item.close for item in series])
    features = calculate_features(series)
    assert slope > 0
    assert r_squared > 0.99
    assert features is not None
    assert features["return_20d"] == pytest.approx(series[-1].close / series[-21].close - 1)
    assert features["return_60d"] == pytest.approx(series[-1].close / series[-61].close - 1)
    assert features["drawdown_20d"] == 0
    assert features["drawdown_60d"] == 0
    assert calculate_atr(series) == pytest.approx(2.0)


def test_breakouts_exclude_the_current_bar():
    series = bars(start=100, step=0, final=101)
    result = calculate_features(series)
    assert result is not None
    assert result["previous_high_20"] == 101  # previous close 100 plus the raw high offset
    assert result["breakout_20d"] is False
    assert result["breakout_55d"] is False
    series[-1] = DailyBar(series[-1].trade_date, 101, 103, 100, 102, 3_000)
    result = calculate_features(series)
    assert result is not None
    assert result["breakout_20d"] is True
    assert result["breakout_55d"] is True


def test_cross_section_scores_and_rs_vs_market():
    first = calculate_features(bars(step=1.2))
    second = calculate_features(bars(step=0.4))
    assert first and second
    rows = []
    for code, item in (("AAA.US", first), ("BBB.US", second)):
        item.update(code=code, rs_20d=item["return_20d"] - 0.02, rs_60d=item["return_60d"] - 0.05)
        item["valid_setup"] = True
        rows.append(item)
    ranked = rank_candidates(rows)
    assert ranked[0]["weighted_slope_percentile"] == 100
    assert ranked[0]["return_20d_percentile"] == 100
    for row in ranked:
        assert 0 <= row["trend_score"] <= 100
        assert 0 <= row["rs_score"] <= 100
        assert 0 <= row["breakout_score"] <= 100
        assert 0 <= row["alpha_score"] <= 100


def test_market_regime_uses_raw_bars_and_own_breadth_universe():
    benchmark = bars(step=1.0)
    result = calculate_market_regime(
        benchmark,
        {"AAA.US": bars(step=1.0), "BBB.US": bars(step=-0.2, start=130)},
        market="US", trade_date=TRADE_DATE, benchmark_code="SPY.US",
    )
    assert result["market_regime"] in {"RISK_ON", "NEUTRAL", "RISK_OFF"}
    assert result["features"]["breadth_ready_count"] == 2
    assert result["features"]["above_ma20_ratio"] == pytest.approx(0.5)
    assert 0 <= result["market_score"] <= 100


def _row(**updates):
    row = {
        "reference_price": 110.0, "atr20": 2.0, "recent_structure_low": 104.0,
        "previous_low_10": 100.0, "ma10": 108.0, "trend_score": 80.0, "rs_score": 80.0,
        "is_candidate": True, "trend_candidate": True,
    }
    row.update(updates)
    return row


def _previous(**updates):
    previous = {
        "state": "HOLDING", "entry_price": 100.0, "last_add_price": 100.0, "units": 1,
        "highest_close": 108.0, "initial_stop": 96.0, "opened_at": date(2026, 8, 1),
        "suggested_initial_weight": 0.1, "suggested_max_weight": 0.1,
    }
    previous.update(updates)
    return previous


def test_atr_risk_levels_and_entry_gate():
    levels = initial_risk_levels(100, 2, 95)
    assert 0 < levels["initial_stop"] < 100
    assert levels["suggested_initial_weight"] <= DEFAULT_CONFIG.single_stock_max_weight
    assert trailing_stop(110, 2) == 105
    assert next_add_price(100, 2) == 101
    entry = transition_state(_row(), None, trade_date=TRADE_DATE, market_regime="RISK_ON")
    assert (entry.state, entry.action, entry.units) == ("ENTRY", "ENTRY", 1)
    blocked = transition_state(_row(), None, trade_date=TRADE_DATE, market_regime="RISK_OFF")
    assert (blocked.state, blocked.action, blocked.units) == ("CANDIDATE", "WATCH", 0)


def test_add_stop_add_reduce_and_exit_transitions():
    added = transition_state(_row(), _previous(), trade_date=TRADE_DATE, market_regime="RISK_ON")
    assert (added.state, added.action, added.units) == ("PYRAMIDING", "ADD", 2)
    risk_off = transition_state(_row(), _previous(), trade_date=TRADE_DATE, market_regime="RISK_OFF")
    assert risk_off.action == "STOP_ADD"
    stopped = transition_state(_row(trend_score=59), _previous(), trade_date=TRADE_DATE, market_regime="RISK_ON")
    assert (stopped.state, stopped.action) == ("WEAKENING", "STOP_ADD")
    reduced = transition_state(
        _row(reference_price=106, ma10=108, rs_score=54, previous_low_10=100),
        _previous(), trade_date=TRADE_DATE, market_regime="RISK_ON",
    )
    assert (reduced.state, reduced.action) == ("REDUCE", "REDUCE")
    exited = transition_state(
        _row(reference_price=95, previous_low_10=96), _previous(), trade_date=TRADE_DATE, market_regime="RISK_ON",
    )
    assert (exited.state, exited.action, exited.units) == ("EXIT", "EXIT", 0)
