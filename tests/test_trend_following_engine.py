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
from finance_analysis.trend_following.regime import calculate_market_regime, realized_volatility_20d  # pragma: allowlist secret
from finance_analysis.trend_following.risk import initial_risk_levels, next_add_price, trailing_stop
from finance_analysis.trend_following.state import apply_exposure_gate, transition_state  # pragma: allowlist secret
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
        "code": "AAA.US", "open": 109.0, "reference_price": 110.0, "atr20": 2.0,
        "recent_structure_low": 104.0, "previous_low_10": 100.0, "ma10": 108.0,
        "trend_score": 80.0, "rs_score": 80.0, "alpha_score": 80.0,
        "is_candidate": True, "trend_candidate": True,
    }
    row.update(updates)
    return row


def _previous(**updates):
    previous = {
        "state": "HOLDING", "entry_price": 100.0, "last_add_price": 100.0, "units": 1,
        "highest_close": 108.0, "initial_stop": 96.0, "trailing_stop": 103.0,
        "next_add_price": 101.0, "opened_at": date(2026, 8, 1),
        "suggested_initial_weight": 0.1, "suggested_max_weight": 0.1,
        "signal_date": date(2026, 7, 31), "signal_price": 99.0,
    }
    previous.update(updates)
    return previous


def test_atr_risk_levels_and_signal_day_is_not_entry():
    levels = initial_risk_levels(100, 2, 95)
    assert 0 < levels["initial_stop"] < 100
    assert levels["suggested_initial_weight"] <= DEFAULT_CONFIG.single_stock_max_weight
    assert trailing_stop(110, 2) == 105
    assert next_add_price(100, 2) == 101
    signal = transition_state(_row(), None, trade_date=TRADE_DATE, market_regime="RISK_ON")
    assert (signal.state, signal.action, signal.units) == ("CANDIDATE", "PENDING_ENTRY", 0)
    assert signal.signal_date == TRADE_DATE
    assert signal.signal_price == 110.0
    assert signal.entry_price is None
    assert signal.opened_at is None
    blocked = transition_state(_row(), None, trade_date=TRADE_DATE, market_regime="RISK_OFF")
    assert (blocked.state, blocked.action, blocked.units) == ("CANDIDATE", "WATCH", 0)


def test_candidate_enters_next_session_at_open_not_signal_close():
    previous = {
        "state": "CANDIDATE", "units": 0, "signal_date": date(2026, 8, 27),
        "signal_price": 100.0, "trade_date": date(2026, 8, 27), "reference_price": 100.0,
    }
    filled = transition_state(
        _row(open=115.0, reference_price=116.0, atr20=2.0),
        previous, trade_date=TRADE_DATE, market_regime="RISK_ON",
    )
    assert (filled.state, filled.action, filled.units) == ("ENTRY", "ENTRY", 1)
    assert filled.entry_price == 115.0
    assert filled.opened_at == TRADE_DATE
    assert filled.signal_date == date(2026, 8, 27)
    assert filled.signal_price == 100.0
    expected_stop = initial_risk_levels(115.0, 2.0, 104.0)["initial_stop"]
    assert filled.initial_stop == expected_stop
    assert filled.next_add_price == next_add_price(115.0, 2.0)
    risk_off = transition_state(
        _row(open=115.0), previous, trade_date=TRADE_DATE, market_regime="RISK_OFF",
    )
    assert (risk_off.state, risk_off.action, risk_off.units) == ("CANDIDATE", "WATCH", 0)
    assert risk_off.entry_price is None


def test_trailing_stop_never_moves_downward_when_atr_expands():
    assert trailing_stop(110, 2) == 105
    assert trailing_stop(110, 4, previous_stop=105) == 105
    held = transition_state(
        _row(reference_price=110, atr20=4.0, is_candidate=False),
        _previous(highest_close=110.0, trailing_stop=105.0, next_add_price=120.0),
        trade_date=TRADE_DATE, market_regime="RISK_ON",
    )
    assert held.trailing_stop >= 105
    assert held.trailing_stop == 105


def test_next_add_price_stays_fixed_until_add_and_ignores_atr_drift():
    expanding = transition_state(
        _row(reference_price=100.4, atr20=4.0),
        _previous(next_add_price=101.0, last_add_price=100.0),
        trade_date=TRADE_DATE, market_regime="RISK_ON",
    )
    assert expanding.action == "HOLD"
    assert expanding.next_add_price == 101.0
    contracting = transition_state(
        _row(reference_price=100.4, atr20=0.5),
        _previous(next_add_price=101.0, last_add_price=100.0),
        trade_date=TRADE_DATE, market_regime="RISK_ON",
    )
    assert contracting.action == "HOLD"
    assert contracting.next_add_price == 101.0
    added = transition_state(
        _row(reference_price=101.2, atr20=2.0),
        _previous(next_add_price=101.0, last_add_price=100.0),
        trade_date=TRADE_DATE, market_regime="RISK_ON",
    )
    assert (added.state, added.action, added.units) == ("PYRAMIDING", "ADD", 2)
    assert added.last_add_price == 101.0
    assert added.next_add_price == next_add_price(101.0, 2.0)


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


def test_regime_exposure_cap_blocks_excess_entry_and_add():
    pending = {
        "state": "CANDIDATE", "units": 0, "signal_date": date(2026, 8, 27), "signal_price": 100.0,
    }
    rows = [
        _row(code="AAA.US", alpha_score=90, open=100),
        _row(code="BBB.US", alpha_score=80, open=100),
        _row(code="CCC.US", alpha_score=70, open=100),
    ]
    desired = {
        row["code"]: transition_state(row, pending, trade_date=TRADE_DATE, market_regime="NEUTRAL")
        for row in rows
    }
    assert all(item.action == "ENTRY" for item in desired.values())
    gated = apply_exposure_gate(rows, desired, {row["code"]: pending for row in rows}, max_exposure=0.2)
    assert gated["AAA.US"].action == "ENTRY"
    assert gated["BBB.US"].action == "ENTRY"
    assert (gated["CCC.US"].state, gated["CCC.US"].action, gated["CCC.US"].units) == (
        "CANDIDATE", "EXPOSURE_BLOCKED", 0,
    )
    add_rows = [_row(code="DDD.US", alpha_score=95), _row(code="EEE.US", alpha_score=60)]
    holding = _previous(units=1, suggested_initial_weight=0.1, next_add_price=101.0)
    add_desired = {
        row["code"]: transition_state(row, holding, trade_date=TRADE_DATE, market_regime="RISK_ON")
        for row in add_rows
    }
    assert all(item.action == "ADD" for item in add_desired.values())
    add_gated = apply_exposure_gate(
        add_rows, add_desired, {row["code"]: holding for row in add_rows}, max_exposure=0.3,
    )
    assert add_gated["DDD.US"].action == "ADD"
    assert add_gated["EEE.US"].action == "EXPOSURE_BLOCKED"
    assert add_gated["EEE.US"].units == 1
    assert add_gated["EEE.US"].next_add_price == 101.0


def test_risk_off_blocks_entry_and_add_but_allows_exit():
    pending = {"state": "CANDIDATE", "units": 0, "signal_date": date(2026, 8, 27), "signal_price": 100.0}
    blocked_entry = transition_state(_row(open=115), pending, trade_date=TRADE_DATE, market_regime="RISK_OFF")
    assert (blocked_entry.state, blocked_entry.action) == ("CANDIDATE", "WATCH")
    blocked_add = transition_state(_row(), _previous(), trade_date=TRADE_DATE, market_regime="RISK_OFF")
    assert blocked_add.action == "STOP_ADD"
    exited = transition_state(
        _row(reference_price=95, previous_low_10=96), _previous(), trade_date=TRADE_DATE, market_regime="RISK_OFF",
    )
    assert (exited.state, exited.action, exited.units) == ("EXIT", "EXIT", 0)


def test_realized_volatility_uses_exactly_20_returns():
    closes = [100.0 + index for index in range(30)]
    recent = closes[-21:]
    expected = recent[1:]
    assert len(recent) == 21
    assert len([right / left - 1 for left, right in zip(recent, expected)]) == 20
    value = realized_volatility_20d(closes)
    import numpy as np
    daily = np.asarray(recent[1:]) / np.asarray(recent[:-1]) - 1.0
    assert len(daily) == 20
    assert value == pytest.approx(float(np.std(daily, ddof=1) * (252 ** 0.5)))
