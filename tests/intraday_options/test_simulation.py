from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

from finance_analysis.integrations.market_data.realtime_state.models import QuoteState
from finance_analysis.intraday_options.simulation import transition, statistics
from finance_analysis.market_stream.session import session_bounds

NOW = datetime(2026, 11, 17, 16, 0, tzinfo=timezone.utc)


def quote(now=NOW, price=100.5):
    return QuoteState(
        "SPY.US", trading_date=now.date(), last_price=Decimal(str(price)), event_time=now, received_at=now
    )


def result(now=NOW, side=1):
    b = dict(
        kind="box_breakout",
        direction="bullish" if side == 1 else "bearish",
        status="confirmed",
        structure_id="breakout:1",
        process_id="process:1",
        trigger=100,
        invalidation=100 - side,
        atr=1,
        confirmed_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=15)).isoformat(),
        measurement_target=100 + 3 * side,
    )
    return dict(
        trading_date=now.date().isoformat(), as_of=now.isoformat(), opportunities=dict(reference=False, branches=[b])
    )


@pytest.mark.parametrize("side", [1, -1])
def test_unique_entry_exit_no_same_cycle_reentry_and_linked_retest(side):
    r = result(side=side)
    state, events = transition({}, "SPY.US", r, quote(price=100 + side * 0.5), NOW)
    assert [e["kind"] for e in events].count("entry") == 1
    frozen = deepcopy(state["position"])
    state, events = transition(
        state, "SPY.US", r, quote(NOW + timedelta(seconds=5), 100 + side * 0.6), NOW + timedelta(seconds=5)
    )
    assert not events
    assert state["position"]["entry_evidence"] == frozen["entry_evidence"]
    r["opportunities"]["branches"][0].update(kind="box_retest", structure_id="retest:1", invalidation=50)
    state, events = transition(
        state, "SPY.US", r, quote(NOW + timedelta(seconds=10), 100 - side * 2), NOW + timedelta(seconds=10)
    )
    assert [e["kind"] for e in events].count("exit") == 1
    assert not state["position"]
    assert next(e for e in events if e["kind"] == "exit")["trade"]["invalidation"] == frozen["invalidation"]
    state, events = transition(
        state, "SPY.US", r, quote(NOW + timedelta(seconds=15), 100 + side * 0.5), NOW + timedelta(seconds=15)
    )
    assert not any(e["kind"] in {"entry", "exit"} for e in events)


@pytest.mark.parametrize("seconds", [-31, 1, 40])
def test_stale_or_future_quote_never_enters(seconds):
    state, events = transition({}, "SPY.US", result(), quote(NOW + timedelta(seconds=seconds)), NOW)
    assert not state.get("position")
    assert not any(e["kind"] == "entry" for e in events)


@pytest.mark.parametrize("price", [98, 102, 104])
def test_live_price_outside_entry_zone(price):
    state, _ = transition({}, "SPY.US", result(), quote(price=price), NOW)
    assert not state.get("position")


@pytest.mark.parametrize("day,hour", [("2026-11-27", 16), ("2025-07-03", 15), ("2026-11-17", 19), ("2026-06-17", 18)])
def test_calendar_cutoff_and_restart_outage_exit(day, hour):
    day = datetime.fromisoformat(day).date()
    bounds = session_bounds("US", day)
    cutoff = bounds[1] - timedelta(hours=2)
    assert cutoff.hour == hour
    before = cutoff - timedelta(minutes=1)
    state, _ = transition({}, "SPY.US", result(before), quote(before), before)
    assert state["position"]
    # Restart after cutoff without any quote, including after a holiday/weekend.
    recovered, events = transition(deepcopy(state), "SPY.US", None, None, cutoff + timedelta(days=3))
    exit_event = next(e for e in events if e["kind"] == "exit")
    assert not recovered["position"]
    assert exit_event["trade"]["estimated"]
    assert exit_event["trade"]["exit_price_at"] == before.isoformat()
    assert exit_event["trade"]["planned_exit_at"] == cutoff.isoformat()
    assert statistics([exit_event["trade"]])[0]["count"] == 0
    _, again = transition(recovered, "SPY.US", None, None, cutoff + timedelta(days=3, seconds=5))
    assert not any(e["kind"] == "exit" for e in again)


def test_target_time_exit_and_protection_only_tightens():
    state, _ = transition({}, "SPY.US", result(), quote(), NOW)
    t = NOW + timedelta(minutes=1)
    state, events = transition(state, "SPY.US", result(t), quote(t, 102.2), t)
    assert state["position"]["protection"] > 99
    protection = state["position"]["protection"]
    t += timedelta(seconds=5)
    state, _ = transition(state, "SPY.US", result(t), quote(t, 102.1), t)
    assert state["position"]["protection"] == protection
    t += timedelta(seconds=5)
    state, events = transition(state, "SPY.US", result(t), quote(t, 103), t)
    assert next(e for e in events if e["kind"] == "exit")["trade"]["exit_reason"] == "到达目标"
    state, _ = transition({}, "SPY.US", result(), quote(), NOW)
    t = NOW + timedelta(minutes=21)
    state, events = transition(state, "SPY.US", result(t), quote(t), t)
    assert "未有效推进" in next(e for e in events if e["kind"] == "exit")["reason"]


def test_opportunity_expiry_does_not_expire_holding():
    state, _ = transition({}, "SPY.US", result(), quote(), NOW)
    t = NOW + timedelta(minutes=16)
    state, events = transition(state, "SPY.US", result(), quote(t), t)
    assert state["position"] and not any(e["kind"] == "exit" for e in events)


def test_revised_process_identity_does_not_reopen_same_window():
    r = result()
    state, _ = transition({}, "SPY.US", r, quote(), NOW)
    t = NOW + timedelta(seconds=5)
    state, _ = transition(state, "SPY.US", r, quote(t, 98), t)
    r["opportunities"]["branches"][0].update(structure_id="revision", process_id="revision")
    t += timedelta(seconds=5)
    state, events = transition(state, "SPY.US", r, quote(t), t)
    assert not state["position"] and not any(e["kind"] == "entry" for e in events)


def test_relative_strength_requires_same_complete_interval_and_qqq_not_applicable():
    from finance_analysis.intraday_options.scheduler import relative_strength
    from tests.intraday_options.test_scoring import candles, START

    bars = candles([0.001] * 30)
    benchmark = candles([0.0005] * 30, symbol="QQQ.US")
    now = START + timedelta(minutes=30, seconds=5)
    values = relative_strength("SPY.US", bars, benchmark, now)
    assert all(r["value"] > 0 for r in values)
    assert all(r["value"] is None for r in relative_strength("QQQ.US", bars, benchmark, now))
    assert all(r["value"] is None for r in relative_strength("SPY.US", bars, benchmark[:-1], now))
