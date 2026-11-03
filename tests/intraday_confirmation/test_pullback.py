"""Ordered, gentle pullback evidence and additive-route regressions."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from test_confirmation import OPEN, SESSION, bar, quote, inputs, Store
from finance_analysis.intraday_confirmation import config
from finance_analysis.intraday_confirmation.engine import metrics, decision, stabilize
from finance_analysis.intraday_confirmation.pullback import pullback_metrics
from finance_analysis.intraday_confirmation.service import ConfirmationService
from finance_analysis.market_review import trading_calendar


def pullback_inputs(touch_minute=5, floor=99.8, scale=1):
    now = OPEN + timedelta(minutes=15)
    dates = trading_calendar.get_trading_days_between(
        "us", SESSION.previous_date - timedelta(days=40), SESSION.previous_date
    )[-10:]
    history = [
        SimpleNamespace(trade_date=d, close=(98 if i < 5 else 100) * scale, volume=10000)
        for i, d in enumerate(dates)
    ]
    bars = [
        replace(
            bar(
                OPEN + timedelta(minutes=i),
                close=101.5,
                high=102 if i < 5 else 101.6,
                low=floor if i == touch_minute else 100.8,
            ),
            open=101.2,
        )
        for i in range(15)
    ]
    q = replace(quote(now, price=101.5, opened=101), low=floor)
    return q, bars, history, now


def observe(**kwargs):
    q, bars, history, now = pullback_inputs(**kwargs)
    return metrics(q, bars, quote(now, price=100), history, SESSION, now)


def test_pullback_can_confirm_without_opening_breakout_and_keeps_stability():
    m = observe()
    assert m["pullback_ma5"] == 100 and m["pullback_ma10"] == 99
    assert m["break_above_opening_range"] is False
    assert m["pullback_touch_time"] == OPEN + timedelta(minutes=6)
    result = decision(m, {})
    assert result["proposed_state"] == "CONFIRMED"
    assert result["conditions"]["ma5_pullback"] and result["conditions"]["price_setup"]
    assert result["score_breakdown"]["price_score"] == 60
    now = OPEN + timedelta(minutes=15)
    first = stabilize(result, {}, now, now)
    assert first["state"] == "WAIT" and first["current_status"] == "PENDING_CONFIRMATION"
    later = now + timedelta(minutes=5)
    assert stabilize(decision(m, {}), first, later, later)["state"] == "CONFIRMED"


@pytest.mark.parametrize("floor", [99.49, 98.9])
def test_deep_pullback_or_ma10_breach_is_not_a_pullback_confirmation(floor):
    m = observe(floor=floor)
    assert m["pullback_ready"] is False
    assert decision(m, {})["proposed_state"] == "WAIT"
    if floor < 99:
        assert m["pullback_holds_ma10"] is False


def test_ma10_is_a_separate_floor_even_inside_the_ma5_band():
    q, bars, history, now = pullback_inputs(floor=99.8)
    for row in history[:5]:
        row.close = 99.8  # MA10=99.9; low is gentle around MA5 but breaks MA10.
    m = metrics(q, bars, quote(now, price=100), history, SESSION, now)
    assert m["pullback_gentle"] is True
    assert m["pullback_holds_ma10"] is False
    assert decision(m, {})["proposed_state"] == "WAIT"


def test_touch_requires_two_later_closes_not_the_touch_bar_itself():
    m = observe(touch_minute=14)
    assert m["pullback_touch_time"] is not None and m["pullback_reclaimed"] is False
    assert decision(m, {})["proposed_state"] == "WAIT"


def test_rebound_from_below_is_not_an_ordered_pullback():
    q, bars, history, _ = pullback_inputs()
    rebound = [replace(b, open=99.8, low=99.8, high=100, close=100) for b in bars]
    # Last two candles recover, but their lows stay above the touch zone.
    rebound[-2:] = [replace(b, open=100.8, low=100.8) for b in bars[-2:]]
    m = pullback_metrics(q, rebound, history, SESSION)
    assert m["pullback_touch_time"] is None and m["pullback_ready"] is False


def test_current_quote_must_remain_above_reclaimed_ma5():
    q, bars, history, now = pullback_inputs()
    m = metrics(replace(q, price=100), bars, quote(now, price=100), history, SESSION, now)
    assert m["pullback_reclaimed"] is False
    assert decision(m, {})["proposed_state"] == "WAIT"


def test_price_alignment_makes_adjusted_history_scale_irrelevant():
    raw, adjusted = observe(), observe(scale=0.5)
    assert adjusted["pullback_ma5"] == raw["pullback_ma5"]
    assert adjusted["pullback_ma10"] == raw["pullback_ma10"]
    assert decision(adjusted, {})["proposed_state"] == "CONFIRMED"


@pytest.mark.parametrize("missing", ["middle_day", "latest_day", "anchor", "close"])
def test_missing_daily_evidence_disables_only_new_route(missing):
    q, bars, history, now = pullback_inputs()
    if missing == "middle_day":
        history.pop(4)
    elif missing == "latest_day":
        history.pop()
    elif missing == "anchor":
        q = replace(q, pre_close=None)
    else:
        history[-1].close = float("nan")
    m = metrics(q, bars, quote(now, price=100), history, SESSION, now)
    assert m["pullback_ready"] is None
    assert decision(m, {})["proposed_state"] == "WAIT"
    breakout = {**inputs(), "pullback_ready": None}
    assert decision(breakout, {})["proposed_state"] == "CONFIRMED"


def test_declining_ma_order_cannot_use_pullback_route():
    q, bars, history, now = pullback_inputs()
    for row in history[:5]:
        row.close = 102
    m = metrics(q, bars, quote(now, price=100), history, SESSION, now)
    assert m["pullback_ma_order"] is False
    assert decision(m, {})["proposed_state"] == "WAIT"


def test_both_routes_do_not_double_count_price_score():
    m = {**observe(), "break_above_opening_range": True}
    assert decision(m, {})["score_breakdown"]["price_score"] == 60


def test_pullback_does_not_bypass_relative_strength_or_missing_minutes():
    m = observe()
    for updated in ({"relative_to_market": 0}, {"data_fresh": False}):
        assert decision({**m, **updated}, {})["proposed_state"] == "WAIT"


def test_existing_v2_pool_is_not_reinterpreted_as_v21(monkeypatch):
    store = Store()
    store.value = {"rule_version": "intraday_v2", "items": [{"code": "ABC.US"}]}
    monkeypatch.setattr("finance_analysis.intraday_confirmation.service.resolve_session", lambda *a: SESSION)
    result = ConfirmationService(store=store, market_data=object()).run("US", OPEN + timedelta(minutes=20))
    assert result["status"] == "skipped"
    assert store.value["rule_version"] == "intraday_v2"
    assert config.RULE_VERSION == "intraday_v2_1"
