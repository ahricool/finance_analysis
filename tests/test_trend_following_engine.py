from __future__ import annotations

from datetime import date, timedelta

import pytest

from finance_analysis.trend_following.state import (  # pragma: allowlist secret
    evaluate_close,
    execute_pending_at_open,
)
from finance_analysis.stocks.reference_data.stock_index import (
    CSI300_STOCK_INDEX,
    CSI500_STOCK_INDEX,
    SP500_STOCK_INDEX,
)
from finance_analysis.trend_following.config import DEFAULT_CONFIG
from finance_analysis.trend_following.features import (  # pragma: allowlist secret
    absolute_trend_passes,
    calculate_atr,
    calculate_features,
    weighted_log_regression,
)
from finance_analysis.trend_following.models import DailyBar
from finance_analysis.trend_following.ranking import rank_candidates
from finance_analysis.trend_following.regime import calculate_market_regime, realized_volatility_20d  # pragma: allowlist secret
from finance_analysis.trend_following.risk import initial_risk_levels, next_add_price, trailing_stop
from finance_analysis.trend_following.scoring import (  # pragma: allowlist secret
    calculate_rs_score,
    calculate_trend_score,
)
from finance_analysis.trend_following.state import (  # pragma: allowlist secret
    apply_exposure_gate,
    apply_regime_exposure_reduction,
    transition_state,
)
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
    assert features["return_5d"] == pytest.approx(series[-1].close / series[-6].close - 1)
    assert features["return_10d"] == pytest.approx(series[-1].close / series[-11].close - 1)
    assert features["return_20d"] == pytest.approx(series[-1].close / series[-21].close - 1)
    assert features["drawdown_20d"] == 0
    assert "return_60d" not in features
    assert "drawdown_60d" not in features
    assert "ma60" not in features
    assert calculate_atr(series) == pytest.approx(2.0)


def test_breakouts_exclude_the_current_bar():
    series = bars(start=100, step=0, final=101)
    result = calculate_features(series)
    assert result is not None
    assert result["previous_high_20"] == 101  # previous close 100 plus the raw high offset
    assert result["breakout_10d"] is False
    assert result["breakout_20d"] is False
    series[-1] = DailyBar(series[-1].trade_date, 101, 103, 100, 102, 3_000)
    result = calculate_features(series)
    assert result is not None
    assert result["breakout_10d"] is True
    assert result["breakout_20d"] is True
    assert "breakout_55d" not in result


def test_cross_section_scores_and_rs_vs_market():
    first = calculate_features(bars(step=1.2))
    second = calculate_features(bars(step=0.4))
    assert first and second
    rows = []
    for code, item in (("AAA.US", first), ("BBB.US", second)):
        item.update(
            code=code,
            rs_5d=item["return_5d"] - 0.005,
            rs_10d=item["return_10d"] - 0.01,
            rs_20d=item["return_20d"] - 0.02,
        )
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


def test_short_horizon_score_weights_and_absolute_trend_three_of_four():
    trend, trend_components = calculate_trend_score({
        "weighted_slope_percentile": 80.0,
        "weighted_r2": 0.9,
        "return_10d": 0.04,
        "return_20d": 0.08,
        "drawdown_20d": -0.04,
    })
    assert trend == pytest.approx(77.0)
    assert set(trend_components) == {
        "weighted_slope_percentile", "weighted_r2", "return_10d", "return_20d", "drawdown_quality",
    }
    rs, rs_components = calculate_rs_score({
        "rs_5d": 0.02,
        "rs_10d": 0.03,
        "rs_20d": 0.04,
        "return_10d_percentile": 70.0,
        "return_20d_percentile": 80.0,
    })
    assert rs == pytest.approx(63.075)
    assert set(rs_components) == {"rs_5d", "rs_10d", "rs_20d", "percentile_10d", "percentile_20d"}
    assert absolute_trend_passes([True, True, True, False]) is True
    assert absolute_trend_passes([True, True, False, False]) is False


def test_short_breakout_and_trend_resume_setups():
    breakout_10 = calculate_features(bars(start=100, step=0))
    assert breakout_10 is not None
    breakout_10.update(
        code="BREAKOUT.US", rs_5d=0.01, rs_10d=0.02, rs_20d=0.03,
    )
    breakout_10["breakout_10d"] = True
    breakout_10["breakout_20d"] = False
    breakout_10["compression_breakout"] = False
    breakout_10["setup"] = "BREAKOUT_10D"
    breakout_10["valid_setup"] = True

    resumed = calculate_features(bars(step=0.5))
    assert resumed is not None
    resumed.update(
        code="RESUME.US", rs_5d=0.01, rs_10d=0.02, rs_20d=0.03,
        breakout_10d=False, breakout_20d=False, compression_breakout=False,
        valid_setup=False, setup="NONE", trend_resume_base=True,
    )
    ranked = rank_candidates([breakout_10, resumed])
    by_code = {row["code"]: row for row in ranked}
    assert by_code["BREAKOUT.US"]["setup"] == "BREAKOUT_10D"
    assert by_code["RESUME.US"]["setup"] == "TREND_RESUME"
    assert by_code["RESUME.US"]["valid_setup"] is True
    assert all(row["setup"] != "BREAKOUT_55D" for row in ranked)


def test_market_regime_uses_raw_bars_and_own_breadth_universe():
    benchmark = bars(step=1.0)
    result = calculate_market_regime(
        benchmark,
        {"AAA.US": bars(step=1.0), "BBB.US": bars(step=-0.2, start=130)},
        market="US", trade_date=TRADE_DATE, benchmark_code="SPY.US",
    )
    assert result["market_regime"] in {"RISK_ON", "NEUTRAL", "RISK_OFF"}
    assert result["features"]["breadth_ready_count"] == 2
    assert result["features"]["above_ma10_ratio"] == pytest.approx(0.5)
    assert result["features"]["above_ma20_ratio"] == pytest.approx(0.5)
    assert "above_ma60_ratio" not in result["features"]
    assert "max_drawdown_60d" not in result["features"]
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
        "alpha_score": 80.0, "rank": 1, "atr": 2.0,
        "features": {"recent_structure_low": 95.0},
        "pending_action": None, "pending_since": None,
        "pending_regime": "RISK_ON", "pending_max_exposure": 1.0,
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
    assert (signal.state, signal.action, signal.units) == ("CANDIDATE", "WATCH", 0)
    assert signal.pending_action == "ENTRY"
    assert signal.signal_date == TRADE_DATE
    assert signal.signal_price == 110.0
    assert signal.entry_price is None
    assert signal.opened_at is None
    blocked = transition_state(_row(), None, trade_date=TRADE_DATE, market_regime="RISK_OFF")
    assert (blocked.state, blocked.action, blocked.units) == ("WATCHING", "WATCH", 0)
    assert blocked.pending_action is None


def test_candidate_enters_next_session_at_open_not_signal_close():
    previous = {
        "state": "CANDIDATE", "units": 0, "signal_date": date(2026, 8, 27),
        "signal_price": 100.0, "trade_date": date(2026, 8, 27), "reference_price": 100.0,
        "action": "PENDING_ENTRY", "pending_action": "ENTRY",
        "pending_regime": "RISK_ON", "pending_max_exposure": 1.0,
        "atr": 2.0, "features": {"recent_structure_low": 104.0},
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
    assert (risk_off.state, risk_off.action, risk_off.units) == ("ENTRY", "ENTRY", 1)
    assert risk_off.entry_price == 115.0


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
    held = _previous(
        next_add_price=111.0, last_add_price=100.0, trailing_stop=90.0,
        highest_close=110.0, initial_stop=80.0,
    )
    expanding = transition_state(
        _row(reference_price=110.4, atr20=4.0, previous_low_10=80.0),
        held, trade_date=TRADE_DATE, market_regime="RISK_ON",
    )
    assert expanding.action == "HOLD"
    assert expanding.next_add_price == 111.0
    contracting = transition_state(
        _row(reference_price=110.4, atr20=0.5, previous_low_10=80.0),
        held, trade_date=TRADE_DATE, market_regime="RISK_ON",
    )
    assert contracting.action == "HOLD"
    assert contracting.next_add_price == 111.0
    added = transition_state(
        _row(reference_price=111.2, atr20=2.0, previous_low_10=80.0),
        held, trade_date=TRADE_DATE, market_regime="RISK_ON",
    )
    assert (added.state, added.action, added.units) == ("HOLDING", "HOLD", 1)
    assert added.pending_action == "ADD"
    executed = transition_state(
        _row(open=112.0, reference_price=113.0, previous_low_10=80.0),
        {**held, "pending_action": "ADD", "pending_since": TRADE_DATE},
        trade_date=TRADE_DATE + timedelta(days=1), market_regime="RISK_ON",
    )
    assert (executed.state, executed.action, executed.units) == ("PYRAMIDING", "ADD", 2)
    assert executed.last_add_price == 112.0
    assert executed.next_add_price == next_add_price(112.0, 2.0)


def test_add_stop_add_reduce_and_exit_transitions():
    added = transition_state(_row(), _previous(), trade_date=TRADE_DATE, market_regime="RISK_ON")
    assert (added.state, added.action, added.units) == ("HOLDING", "HOLD", 1)
    assert added.pending_action == "ADD"
    risk_off = transition_state(_row(), _previous(), trade_date=TRADE_DATE, market_regime="RISK_OFF")
    assert risk_off.action == "STOP_ADD"
    stopped = transition_state(_row(trend_score=59), _previous(), trade_date=TRADE_DATE, market_regime="RISK_ON")
    assert (stopped.state, stopped.action) == ("WEAKENING", "STOP_ADD")
    reduced = transition_state(
        _row(reference_price=106, ma10=108, rs_score=54, previous_low_10=100),
        _previous(), trade_date=TRADE_DATE, market_regime="RISK_ON",
    )
    assert (reduced.state, reduced.action, reduced.units) == ("WEAKENING", "HOLD", 1)
    assert reduced.pending_action == "REDUCE"
    reduced_at_open = transition_state(
        _row(reference_price=106, ma10=108, rs_score=54, previous_low_10=100),
        _previous(units=3, pending_action="REDUCE", pending_since=TRADE_DATE - timedelta(days=1)),
        trade_date=TRADE_DATE, market_regime="RISK_ON",
    )
    assert (reduced_at_open.state, reduced_at_open.action, reduced_at_open.units) == ("REDUCE", "REDUCE", 2)
    exited = transition_state(
        _row(reference_price=95, previous_low_10=96), _previous(), trade_date=TRADE_DATE, market_regime="RISK_ON",
    )
    assert (exited.state, exited.action, exited.units) == ("WEAKENING", "HOLD", 1)
    assert exited.pending_action == "EXIT"
    exited_at_open = transition_state(
        _row(reference_price=95, previous_low_10=96),
        _previous(pending_action="EXIT", pending_since=TRADE_DATE - timedelta(days=1)),
        trade_date=TRADE_DATE, market_regime="RISK_ON",
    )
    assert (exited_at_open.state, exited_at_open.action, exited_at_open.units) == ("EXIT", "EXIT", 0)


def test_regime_exposure_cap_blocks_excess_entry_and_add():
    pending = {
        "state": "CANDIDATE", "units": 0, "signal_date": date(2026, 8, 27), "signal_price": 100.0,
        "action": "PENDING_ENTRY", "pending_action": "ENTRY",
        "pending_regime": "NEUTRAL", "pending_max_exposure": 0.2,
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
    assert (gated["CCC.US"].action, gated["CCC.US"].units) == ("EXPOSURE_BLOCKED", 0)
    add_rows = [_row(code="DDD.US", alpha_score=95), _row(code="EEE.US", alpha_score=60)]
    holding = _previous(
        units=1,
        suggested_initial_weight=0.025,
        suggested_max_weight=0.1,
        next_add_price=101.0,
        pending_action="ADD",
        pending_since=TRADE_DATE - timedelta(days=1),
        pending_max_exposure=0.075,
    )
    add_desired = {
        row["code"]: transition_state(row, holding, trade_date=TRADE_DATE, market_regime="RISK_ON")
        for row in add_rows
    }
    assert all(item.action == "ADD" for item in add_desired.values())
    add_gated = apply_exposure_gate(
        add_rows, add_desired, {row["code"]: holding for row in add_rows}, max_exposure=0.075,
    )
    assert add_gated["DDD.US"].action == "ADD"
    assert add_gated["EEE.US"].action == "EXPOSURE_BLOCKED"
    assert add_gated["EEE.US"].units == 1
    assert add_gated["EEE.US"].next_add_price == 101.0


def test_risk_off_blocks_entry_and_add_but_allows_exit():
    pending = {
        "state": "CANDIDATE", "units": 0, "signal_date": date(2026, 8, 27),
        "signal_price": 100.0, "action": "PENDING_ENTRY", "pending_action": "ENTRY",
        "pending_regime": "RISK_ON", "pending_max_exposure": 1.0,
    }
    blocked_entry = transition_state(_row(open=115), pending, trade_date=TRADE_DATE, market_regime="RISK_OFF")
    assert (blocked_entry.state, blocked_entry.action, blocked_entry.units) == ("ENTRY", "ENTRY", 1)
    blocked_add = transition_state(_row(), _previous(), trade_date=TRADE_DATE, market_regime="RISK_OFF")
    assert blocked_add.action == "STOP_ADD"
    exited = transition_state(
        _row(reference_price=95, previous_low_10=96), _previous(), trade_date=TRADE_DATE, market_regime="RISK_OFF",
    )
    assert (exited.state, exited.action, exited.units) == ("WEAKENING", "HOLD", 1)
    assert exited.pending_action == "EXIT"
    executed = transition_state(
        _row(reference_price=95, previous_low_10=96),
        _previous(pending_action="EXIT", pending_since=TRADE_DATE - timedelta(days=1)),
        trade_date=TRADE_DATE, market_regime="RISK_OFF",
    )
    assert (executed.state, executed.action, executed.units) == ("EXIT", "EXIT", 0)


def test_risk_off_reduces_excess_exposure_without_forcing_immediate_exit():
    rows = [
        _row(code="WEAK.US", rank=20, alpha_score=60.0),
        _row(code="STRONG.US", rank=1, alpha_score=90.0),
    ]
    decisions = {
        row["code"]: transition_state(
            row,
            _previous(units=2, suggested_initial_weight=0.1, suggested_max_weight=0.2),
            trade_date=TRADE_DATE,
            market_regime="RISK_OFF",
        )
        for row in rows
    }
    reduced = apply_regime_exposure_reduction(
        rows,
        decisions,
        trade_date=TRADE_DATE,
        market_regime="RISK_OFF",
        max_exposure=DEFAULT_CONFIG.regime_max_exposure["RISK_OFF"],
    )
    assert DEFAULT_CONFIG.regime_max_exposure["RISK_OFF"] == 0.2
    assert reduced["WEAK.US"].pending_action == "REDUCE"
    assert reduced["STRONG.US"].pending_action == "REDUCE"
    assert all(item.action != "EXIT" and item.units == 2 for item in reduced.values())


def test_entry_allocation_uses_signal_day_alpha_not_execution_day_close_alpha():
    rows = [
        _row(code="AAA.US", alpha_score=60.0),
        _row(code="BBB.US", alpha_score=95.0),
    ]
    previous = {
        "AAA.US": {
            "state": "CANDIDATE", "units": 0, "signal_date": date(2026, 8, 27),
            "signal_price": 100.0, "pending_action": "ENTRY", "alpha_score": 90.0,
            "rank": 1, "atr": 2.0, "features": {"recent_structure_low": 95.0},
            "pending_regime": "RISK_ON", "pending_max_exposure": 0.1,
        },
        "BBB.US": {
            "state": "CANDIDATE", "units": 0, "signal_date": date(2026, 8, 27),
            "signal_price": 100.0, "pending_action": "ENTRY", "alpha_score": 80.0,
            "rank": 2, "atr": 2.0, "features": {"recent_structure_low": 95.0},
            "pending_regime": "RISK_ON", "pending_max_exposure": 0.1,
        },
    }
    desired = {
        row["code"]: transition_state(
            row, previous[row["code"]], trade_date=TRADE_DATE, market_regime="RISK_ON",
        )
        for row in rows
    }
    gated = apply_exposure_gate(rows, desired, previous, max_exposure=0.1)
    assert gated["AAA.US"].action == "ENTRY"
    assert gated["BBB.US"].action == "EXPOSURE_BLOCKED"


def test_single_stock_max_weight_blocks_add_without_incrementing_units():
    row = _row(code="AAA.US", open=112.0)
    capped = _previous(
        units=1, suggested_initial_weight=0.1, suggested_max_weight=0.1,
        pending_action="ADD", pending_since=TRADE_DATE - timedelta(days=1),
    )
    desired = transition_state(row, capped, trade_date=TRADE_DATE, market_regime="RISK_ON")
    assert desired.units == 2
    gated = apply_exposure_gate([row], {"AAA.US": desired}, {"AAA.US": capped}, max_exposure=1.0)
    assert gated["AAA.US"].action == "EXPOSURE_BLOCKED"
    assert gated["AAA.US"].units == 1
    assert "single-stock" in gated["AAA.US"].reasons[-1]

    four_unit = _previous(
        units=3, suggested_initial_weight=0.025, suggested_max_weight=0.1,
        pending_action="ADD", pending_since=TRADE_DATE - timedelta(days=1),
    )
    desired_four = transition_state(row, four_unit, trade_date=TRADE_DATE, market_regime="RISK_ON")
    allowed = apply_exposure_gate(
        [row], {"AAA.US": desired_four}, {"AAA.US": four_unit}, max_exposure=1.0,
    )
    assert (allowed["AAA.US"].action, allowed["AAA.US"].units) == ("ADD", 4)


def test_missing_active_code_still_consumes_portfolio_exposure():
    entry_row = _row(code="BBB.US")
    previous = {
        "AAA.US": _previous(units=1, suggested_initial_weight=0.1, suggested_max_weight=0.1),
        "BBB.US": {
            "state": "CANDIDATE", "units": 0, "signal_date": date(2026, 8, 27),
            "signal_price": 100.0, "pending_action": "ENTRY", "alpha_score": 80.0,
            "rank": 2, "atr": 2.0, "features": {"recent_structure_low": 95.0},
            "pending_regime": "RISK_ON", "pending_max_exposure": 0.1,
        },
    }
    desired = transition_state(
        entry_row, previous["BBB.US"], trade_date=TRADE_DATE, market_regime="RISK_ON",
    )
    gated = apply_exposure_gate(
        [entry_row], {"BBB.US": desired}, previous, max_exposure=0.1,
    )
    assert gated["BBB.US"].action == "EXPOSURE_BLOCKED"


def test_previous_regime_controls_entry_even_when_current_close_is_risk_off():
    signal = transition_state(
        _row(), None, trade_date=date(2026, 8, 1), market_regime="RISK_ON",
    )
    executed = transition_state(
        _row(),
        {
            **signal.to_dict(),
            "atr": 2.0,
            "features": {"recent_structure_low": 104.0},
            "market_regime": "RISK_ON",
        },
        trade_date=date(2026, 8, 2),
        market_regime="RISK_OFF",
    )
    assert (executed.state, executed.action, executed.units) == ("ENTRY", "ENTRY", 1)
    assert executed.pending_action is None


def test_previous_exposure_cap_controls_open_allocation_not_current_close_cap():
    rows = [_row(code="AAA.US"), _row(code="BBB.US")]
    previous = {
        code: {
            "state": "CANDIDATE", "action": "WATCH", "units": 0,
            "signal_date": date(2026, 8, 27), "signal_price": 100.0,
            "pending_action": "ENTRY", "pending_regime": "NEUTRAL",
            "pending_max_exposure": 0.1, "alpha_score": 90.0 - index,
            "rank": index + 1, "atr": 2.0, "features": {"recent_structure_low": 95.0},
        }
        for index, code in enumerate(("AAA.US", "BBB.US"))
    }
    opened = {
        row["code"]: execute_pending_at_open(
            row, previous[row["code"]], trade_date=TRADE_DATE,
        )
        for row in rows
    }
    allocated = apply_exposure_gate(rows, opened, previous)
    assert allocated["AAA.US"].action == "ENTRY"
    assert allocated["BBB.US"].action == "EXPOSURE_BLOCKED"
    final = evaluate_close(
        rows[0], allocated["AAA.US"], trade_date=TRADE_DATE,
        market_regime="RISK_OFF", max_exposure=0.0,
    )
    assert final.action == "ENTRY"
    assert final.units == 1


def test_entry_execution_can_generate_same_day_pending_exit():
    previous = {
        "state": "CANDIDATE", "action": "WATCH", "units": 0,
        "signal_date": date(2026, 8, 27), "signal_price": 100.0,
        "pending_action": "ENTRY", "pending_regime": "RISK_ON",
        "pending_max_exposure": 1.0, "alpha_score": 90.0, "rank": 1,
        "atr": 2.0, "features": {"recent_structure_low": 95.0},
    }
    result = transition_state(
        _row(open=100.0, reference_price=90.0, previous_low_10=92.0),
        previous, trade_date=TRADE_DATE, market_regime="RISK_OFF", max_exposure=0.0,
    )
    assert (result.action, result.units, result.pending_action) == ("ENTRY", 1, "EXIT")
    next_day = transition_state(
        _row(open=89.0, reference_price=88.0),
        result.to_dict(), trade_date=TRADE_DATE + timedelta(days=1), market_regime="RISK_OFF",
    )
    assert (next_day.action, next_day.units) == ("EXIT", 0)


def test_add_execution_can_generate_reduce_and_reduce_can_repeat():
    prior_add = _previous(
        units=1, initial_stop=80.0, trailing_stop=80.0, next_add_price=101.0,
        pending_action="ADD", pending_since=TRADE_DATE - timedelta(days=1),
        pending_regime="RISK_ON", pending_max_exposure=1.0,
        suggested_initial_weight=0.025, suggested_max_weight=0.1,
    )
    added = transition_state(
        _row(open=101.0, reference_price=106.0, previous_low_10=80.0, ma10=108.0, rs_score=54.0),
        prior_add, trade_date=TRADE_DATE, market_regime="NEUTRAL",
    )
    assert (added.action, added.units, added.pending_action) == ("ADD", 2, "REDUCE")

    prior_reduce = _previous(
        units=3, initial_stop=80.0, trailing_stop=80.0, next_add_price=120.0,
        pending_action="REDUCE", pending_since=TRADE_DATE - timedelta(days=1),
        pending_regime="RISK_OFF", pending_max_exposure=0.0,
    )
    reduced = transition_state(
        _row(reference_price=106.0, previous_low_10=80.0, ma10=108.0, rs_score=54.0),
        prior_reduce, trade_date=TRADE_DATE, market_regime="RISK_OFF",
    )
    assert (reduced.action, reduced.units, reduced.pending_action) == ("REDUCE", 2, "REDUCE")


def test_candidate_expiry_configuration_only_supports_one_session():
    with pytest.raises(ValueError, match="candidate_expiry_sessions=1"):
        type(DEFAULT_CONFIG)(candidate_expiry_sessions=2)


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
