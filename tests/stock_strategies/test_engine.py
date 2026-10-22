from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta

import pytest

from finance_analysis.stock_strategies.engine import advance, executable, initial_state
from finance_analysis.stock_strategies.features import DataNotReady, indicators, wilder
from finance_analysis.stock_strategies.registry import STRATEGIES, parameters
from finance_analysis.stock_strategies.signals import decide
from .helpers import inputs

MA = STRATEGIES[0]
DAY = date(2026, 10, 19)


def test_prior_close_selection_next_open_fills_and_cash_conservation():
    data = inputs()
    state, first = advance(MA, initial_state(), data, DAY)
    assert first["payload"]["fills"] == []
    assert first["nav"] == 1e6
    data = inputs(DAY + timedelta(days=1), {"A.US": (110, 121), "B.US": (100, 200), "SPY.US": (100, 100)})
    # The current close would prefer B; only the previously frozen rank may select A.
    data.features["B.US"]["ma20"] = 180
    state, second = advance(MA, state, data, DAY)
    assert list(state["positions"]) == ["A.US"]
    assert second["nav"] == pytest.approx(1.1e6)
    assert second["daily_return"] == pytest.approx(0.1)
    assert second["payload"]["fills"][0]["price"] == 110
    assert second["cagr"] is None
    assert second["nav"] == pytest.approx(
        state["cash"] + sum(p["quantity"] * p["mark"] for p in state["positions"].values())
    )


def test_adjustment_scale_bridge_preserves_value_and_adjusts_pending_atr():
    state, _ = advance(STRATEGIES[2], initial_state(), inputs(), DAY)
    data = inputs(
        DAY + timedelta(days=1),
        {"A.US": (50, 50), "B.US": (50, 50), "SPY.US": (100, 100)},
        {"A.US": 50, "B.US": 50, "SPY.US": 100},
    )
    state, snapshot = advance(STRATEGIES[2], state, data, DAY)
    assert snapshot["nav"] == pytest.approx(1e6)
    assert state["positions"]["A.US"]["quantity"] == pytest.approx(20000)
    state["plan"]["exits"] = {}  # isolate rebasing from the deliberately fixed mock MA values
    old = deepcopy(state)
    data = inputs(
        DAY + timedelta(days=2),
        {"A.US": (25, 25), "B.US": (25, 25), "SPY.US": (100, 100)},
        {"A.US": 25, "B.US": 25, "SPY.US": 100},
    )
    state, snapshot = advance(STRATEGIES[2], state, data, DAY)
    assert snapshot["nav"] == pytest.approx(1e6)
    assert state["positions"]["A.US"]["entry_price"] == 25
    assert snapshot["payload"]["adjustments"][0]["scale"] == 0.5
    assert old["positions"]["A.US"]["quantity"] == 20000


def test_one_fill_per_symbol_per_day_and_pending_sell_survives_blocked_open():
    state, _ = advance(MA, initial_state(), inputs(), DAY)
    state, _ = advance(MA, state, inputs(DAY + timedelta(days=1)), DAY)
    state["plan"]["exits"] = {"A.US": ["test exit"]}
    data = inputs(DAY + timedelta(days=2))
    data.features["A.US"]["open"] = float("nan")
    state, snap = advance(MA, state, data, DAY)
    assert state["positions"]["A.US"]["pending_exit"] == ["test exit"]
    assert snap["payload"]["blocked"][0]["action"] == "SELL"
    data = inputs(DAY + timedelta(days=3))
    state, snap = advance(MA, state, data, DAY)
    assert [r["action"] for r in snap["payload"]["fills"] if r["code"] == "A.US"] == ["SELL"]


def test_account_dd_strictness_pause_sessions_and_lifetime_peak():
    spec = replace(MA, account_dd=0.25, cooldown=2)
    state, _ = advance(spec, initial_state(), inputs(), DAY)
    state, _ = advance(spec, state, inputs(DAY + timedelta(days=1)), DAY)
    data = inputs(DAY + timedelta(days=2), {"A.US": (100, 75), "B.US": (100, 100), "SPY.US": (100, 100)})
    state, _ = advance(spec, state, data, DAY)
    assert not state["stopped"]  # strict >25%, exactly25 does not trigger.
    state["plan"]["exits"] = {}  # isolate account DD from MA exit
    data = inputs(
        DAY + timedelta(days=3),
        {"A.US": (75, 74), "B.US": (100, 100), "SPY.US": (100, 100)},
        {"A.US": 75, "B.US": 100, "SPY.US": 100},
    )
    state, _ = advance(spec, state, data, DAY)
    assert state["pause_remaining"] == 2
    for offset, price in ((4, 74), (5, 74)):
        data = inputs(
            DAY + timedelta(days=offset),
            {"A.US": (price, price), "B.US": (100, 100), "SPY.US": (100, 100)},
            {"A.US": price, "B.US": 100, "SPY.US": 100},
        )
        state, _ = advance(spec, state, data, DAY)
        assert not state["positions"]
    data = inputs(
        DAY + timedelta(days=6),
        {"A.US": (100, 100), "B.US": (100, 100), "SPY.US": (100, 100)},
        {"A.US": 74, "B.US": 100, "SPY.US": 100},
    )
    state, _ = advance(spec, state, data, DAY)
    assert state["positions"]
    assert state["cycle_peak"] == pytest.approx(740000)
    assert state["nav_peak"] == 1e6
    assert state["max_drawdown"] == pytest.approx(-0.26)


def test_monthly_momentum_and_regression_have_different_entry_schedules():
    data = inputs()
    assert not decide(STRATEGIES[3], initial_state(), data)["candidates"]
    assert decide(STRATEGIES[1], initial_state(), data)["candidates"]
    data.month_end = True
    assert decide(STRATEGIES[3], initial_state(), data)["candidates"]


def test_breadth_is_qualified_ma50_fraction_and_two_close_exit():
    data = inputs()
    spec = parameters(STRATEGIES[-1], "US")
    for f in data.features.values():
        f["ma50"] = 101
    state = initial_state()
    decision = decide(spec, state, data)
    assert decision["breadth"] == 0
    assert decision["breadth_denominator"] == 2
    assert decision["candidates"] == []
    state["breadth_bad"] = 1
    decision = decide(spec, state, data)
    assert "MA50广度连续两日低于25%" in decision["exits"]["A.US"]


def test_context_missing_is_waiting_and_does_not_mutate_input_state():
    state = initial_state()
    original = deepcopy(state)
    data = inputs()
    data.etf_regime = None
    with pytest.raises(DataNotReady):
        advance(STRATEGIES[1], state, data, DAY)
    assert state == original


def test_wilder_sma_seed_and_gap_reset_and_indicator_gaps_not_compressed():
    assert wilder([1, 2, 3, 4], 3) == pytest.approx(8 / 3)
    assert not __import__("math").isfinite(wilder([1, 2, 3, float("nan"), 4], 3))
    days = [DAY + timedelta(days=i) for i in range(210)]
    rows = [dict(date=d, open=100, high=101, low=99, close=100, volume=1000, amount=None) for d in days]
    assert indicators(rows, days)["ma200"] == 100
    assert not __import__("math").isfinite(indicators(rows[:100] + rows[101:], days)["ma200"])


def test_cn_limit_proxy_checks_adjusted_previous_close():
    data = inputs(market="CN")
    data.instruments["600000.SH"] = dict(type="STOCK", name="测试")
    data.features["600000.SH"] = dict(open=110, previous_close=100, volume=1000)
    assert not executable(data, "600000.SH", "BUY")
    assert executable(data, "600000.SH", "SELL")


def test_execution_does_not_use_current_volume_or_close_for_buy_selection():
    state, _ = advance(STRATEGIES[2], initial_state(), inputs(), DAY)
    data = inputs(DAY + timedelta(days=1))
    data.features["A.US"]["volume"] = 0
    data.features["A.US"]["close"] = 200
    state, snapshot = advance(STRATEGIES[2], state, data, DAY)
    assert snapshot["payload"]["fills"][0]["code"] == "A.US"
    assert snapshot["payload"]["fills"][0]["price"] == 100


def test_ma_stock_and_etf_rank_together_instead_of_stock_priority():
    data = inputs()
    data.etfs = ("QQQ.US",)
    data.features["QQQ.US"] = dict(data.features["B.US"], ma20=99, ma50=70)
    data.instruments["QQQ.US"] = dict(type="ETF", name="QQQ")
    result = decide(MA, initial_state(), data)
    assert result["candidates"][0]["code"] == "QQQ.US"


def test_growth_board_st_uses_20_percent_limit():
    data = inputs(market="CN")
    data.instruments["300001.SZ"] = dict(type="STOCK", name="ST测试")
    data.features["300001.SZ"] = dict(open=110, previous_close=100)
    assert executable(data, "300001.SZ", "BUY")
    data.features["300001.SZ"]["open"] = 120
    assert not executable(data, "300001.SZ", "BUY")


def test_blocked_exit_does_not_block_other_slot_and_open_valuation_uses_limit_down_price():
    data = inputs(DAY + timedelta(days=1), market="CN")
    mapping = {"A.US": "600000.SH", "B.US": "600001.SH", "SPY.US": "510300.SH"}
    data.features = {mapping[c]: f for c, f in data.features.items()}
    data.instruments = {mapping[c]: meta for c, meta in data.instruments.items()}
    data.prices = {mapping[c]: marks for c, marks in data.prices.items()}
    data.stocks, data.etfs, data.breadth_codes = ("600000.SH", "600001.SH"), (), ("600000.SH", "600001.SH")
    data.benchmark = "510300.SH"
    data.features["600000.SH"].update(open=90, close=90)
    state = initial_state()
    state.update(
        cash=900000,
        sessions=1,
        positions={
            "600000.SH": dict(
                quantity=1000,
                entry_price=100,
                name="A",
                mark=100,
                mark_date=DAY.isoformat(),
                peak=100,
                stop=None,
                pending_exit=[],
            )
        },
        plan=dict(
            signal_date=DAY.isoformat(),
            execution_date=data.day.isoformat(),
            status="READY",
            candidates=[dict(code="600001.SH", name="B", atr=5, signal_close=100)],
            exits={"600000.SH": ["exit"]},
        ),
    )
    updated, snapshot = advance(replace(MA, slots=2, account_dd=0), state, data, DAY)
    assert updated["positions"]["600000.SH"]["pending_exit"] == ["exit"]
    assert updated["positions"]["600001.SH"]["quantity"] == pytest.approx(4950)
    assert snapshot["nav"] == pytest.approx(990000)


def hybrid_data():
    data = inputs(market="CN")
    data.etfs = ("QQQ.US",)
    data.features["QQQ.US"] = dict(data.features["B.US"], close=99)
    data.instruments["QQQ.US"] = dict(type="ETF", name="ETF")
    data.trends = {
        40: {"QQQ.US": dict(trend_score=70, rs_score=60)},
        60: {c: dict(trend_score=70, rs_score=60) for c in data.stocks},
    }
    return data


def test_hybrid_stock_priority_etf_strength_and_independent_market_exit():
    data = hybrid_data()
    spec = STRATEGIES[5]
    decision = decide(spec, initial_state(), data)
    assert [r["code"] for r in decision["candidates"]] == ["A.US", "B.US", "QQQ.US"]
    data.regimes[20]["score"] = 59
    decision = decide(spec, initial_state(), data)
    assert "市场分数低于60或ETF非风险开启" in decision["exits"]["A.US"]
    assert not decision["exits"]["QQQ.US"]
    assert [r["code"] for r in decision["candidates"]] == ["QQQ.US"]
    data.trends[40]["QQQ.US"]["trend_score"] = 59
    assert not decide(spec, initial_state(), data)["candidates"]


def test_hybrid_breakout_filters_original_top40_without_replenishing():
    data = hybrid_data()
    data.stocks = tuple(f"X{i:02d}.US" for i in range(41))
    data.trends[60] = {c: dict(trend_score=90 - i / 10, rs_score=70) for i, c in enumerate(data.stocks)}
    for code in data.stocks:
        data.features[code] = dict(data.features["A.US"])
        data.instruments[code] = dict(type="STOCK", name=code)
    data.features[data.stocks[-1]]["previous_high"] = 99
    result = decide(STRATEGIES[6], initial_state(), data)
    assert [r["code"] for r in result["candidates"]] == ["QQQ.US"]


def test_breadth_native_parent_parameters_are_separate():
    cn = parameters(STRATEGIES[-1], "CN")
    us = parameters(STRATEGIES[-1], "US")
    assert (cn.family, cn.atr, cn.account_dd, cn.cooldown) == ("hybrid", 3, 0, 0)
    assert (us.family, us.atr, us.account_dd, us.cooldown) == ("regression", 0, 0.2, 20)
    assert cn.source_id("CN") != us.source_id("US")


def test_regression_two_close_macro_exit_and_reset():
    data = inputs()
    data.regimes[60] = dict(regime="RISK_OFF", score=20)
    data.etf_regime = "RISK_OFF"
    state = initial_state()
    first = decide(STRATEGIES[1], state, data)
    assert not first["exits"]["A.US"]
    state["macro_bad"] = 1
    second = decide(STRATEGIES[1], state, data)
    assert "ETF与Trend60连续两日风险关闭" in second["exits"]["A.US"]
    assert not second["candidates"]
    data.etf_regime = "NEUTRAL"
    assert decide(STRATEGIES[1], state, data)["macro_bad"] == 0


def test_20261020_exact_20percent_dd_uses_nav_threshold_without_subtraction_roundoff():
    spec = replace(STRATEGIES[1], slots=1)
    state, _ = advance(spec, initial_state(), inputs(), DAY)
    state, _ = advance(spec, state, inputs(DAY + timedelta(days=1)), DAY)
    data = inputs(DAY + timedelta(days=2), {"A.US": (100, 80), "B.US": (100, 100), "SPY.US": (100, 100)})
    state, snapshot = advance(spec, state, data, DAY)
    assert state["nav"] == 800000
    assert state["stopped"] and state["pause_remaining"] == 20
    assert "账户回撤触发清仓与暂停" in snapshot["payload"]["plan"]["exits"]["A.US"]
