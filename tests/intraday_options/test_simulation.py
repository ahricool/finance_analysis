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


def test_held_opportunity_remains_valid_without_duplicate_entry_and_symbols_are_independent():
    spy, _ = transition({}, "SPY.US", result(), quote(), NOW)
    nvda, _ = transition({}, "NVDA.US", result(), quote(), NOW)
    assert spy["position"] and nvda["position"]
    assert spy["position"]["id"] != nvda["position"]["id"]
    for symbol, state in [("SPY.US", spy), ("NVDA.US", nvda)]:
        assert state["plans"][0]["opportunity_valid"]
        assert not state["plans"][0]["executable"]
        later = NOW + timedelta(seconds=5)
        updated, events = transition(state, symbol, result(), quote(later), later)
        assert updated["plans"][0]["opportunity_valid"]
        assert not updated["plans"][0]["executable"]
        assert not any(e["kind"] == "entry" for e in events)


@pytest.mark.parametrize("failure", ["invalidated", "expired", "extended", "quote", "minutes"])
def test_held_opportunity_validity_degrades_independently(failure):
    state, _ = transition({}, "SPY.US", result(), quote(), NOW)
    later = NOW + timedelta(seconds=5)
    r = result()
    q = quote(later)
    if failure in {"invalidated", "expired", "extended"}:
        r["opportunities"]["branches"][0]["status"] = failure
    elif failure == "quote":
        q = quote(NOW - timedelta(seconds=31))
    else:
        r["as_of"] = (NOW - timedelta(minutes=2)).isoformat()
    state, _ = transition(state, "SPY.US", r, q, later)
    assert state["position"]
    assert not state["plans"][0]["opportunity_valid"]
    assert not state["plans"][0]["executable"]


@pytest.mark.parametrize("day", ["2026-11-17", "2026-11-27"])
@pytest.mark.parametrize("scenario", ["normal", "late_recovery", "stale_price", "interrupted"])
def test_cutoff_classifies_actual_price_and_processing_continuity(day, scenario):
    cutoff = session_bounds("US", datetime.fromisoformat(day).date())[1] - timedelta(hours=2)
    before = cutoff - timedelta(seconds=3)
    state, _ = transition({}, "SPY.US", result(before), quote(before, 100.5), before)
    if scenario == "stale_price":
        state["position"]["last_price_at"] = (cutoff - timedelta(seconds=60)).isoformat()
    elif scenario == "interrupted":
        state["healthy"] = False
    now = cutoff + timedelta(seconds=120 if scenario == "late_recovery" else 2)
    state, events = transition(state, "SPY.US", result(now), quote(now - timedelta(seconds=1), 105), now)
    closed = next(e["trade"] for e in events if e["kind"] == "exit")
    assert closed["estimated"] == (scenario != "normal")
    assert closed["exit_price"] == 100.5  # Never use the post-cutoff 105 quote.
    assert closed["exit_price_at"] <= cutoff.isoformat()
    assert closed["exit_at"] == now.isoformat()
    assert closed["planned_exit_at"] == cutoff.isoformat()
    assert not state["position"] and state["stopped"]
    assert statistics([closed])[0]["count"] == (1 if scenario == "normal" else 0)


@pytest.mark.parametrize(
    "at,phase",
    [
        ("2026-11-17T11:00:00+00:00", "preopen"),
        ("2026-11-17T14:29:59+00:00", "preopen"),
        ("2026-11-17T19:00:00+00:00", "stopped"),
        ("2026-11-17T21:00:00+00:00", "closed"),
        ("2026-11-21T16:00:00+00:00", "closed"),
        ("2026-11-26T16:00:00+00:00", "closed"),
        ("2026-11-27T16:00:00+00:00", "stopped"),
    ],
)
def test_inactive_window_never_emits_confirmations_or_data_messages(at, phase):
    now = datetime.fromisoformat(at)
    state = {}
    for seconds in (0, 5, 35, 40, 60, 90):
        t = now + timedelta(seconds=seconds)
        if phase == "preopen" and t >= session_bounds("US", now.date())[0]:
            break
        q = quote(t) if seconds % 2 else None
        state, events = transition(state, "SPY.US", result(t), q, t)
        assert not events
        assert state["session_phase"] == phase
        assert state["stopped"] and not state.get("position")
        assert not state["confirmations"]
        assert not any(p["opportunity_valid"] for p in state["plans"])


def test_open_rejects_fresh_premarket_quote_and_accepts_regular_session_quote():
    opening = session_bounds("US", NOW.date())[0]
    state, events = transition({}, "SPY.US", result(opening), quote(opening - timedelta(seconds=1)), opening)
    assert not state.get("position") and not any(e["kind"] == "entry" for e in events)
    state, events = transition(state, "SPY.US", result(opening), quote(opening), opening)
    assert state["position"]


def test_short_quote_expiry_blocks_entry_without_flapping_messages():
    # Reproduce a sparse quote crossing 30 seconds and recovering every 40 seconds.
    state = {}
    for second in range(0, 211, 5):
        t = NOW + timedelta(seconds=second)
        q = quote(NOW + timedelta(seconds=second // 40 * 40))
        state, events = transition(state, "SPY.US", None, q, t)
        assert not any(e["kind"] == "data" for e in events)
    # Use a pending valid opportunity to prove message debounce never loosens execution.
    state, events = transition({}, "SPY.US", result(), quote(NOW - timedelta(seconds=31)), NOW)
    assert not state.get("position")
    assert not state["plans"][0]["opportunity_valid"]
    assert state["data_issue"] == "报价或接收时间已过期"


def test_sustained_data_incident_and_stable_recovery_survive_restart():
    state, events = transition({}, "SPY.US", None, None, NOW)
    assert not events
    for second in (10, 20):
        state, events = transition(state, "SPY.US", None, None, NOW + timedelta(seconds=second))
        assert not events
    t = NOW + timedelta(seconds=30)
    state, events = transition(deepcopy(state), "SPY.US", None, None, t)
    assert len(events) == 1 and "行情异常" in events[0]["reason"]
    assert events[0]["issue"] == "报价缺失或时间字段无效"
    # A brief recovery does not emit 'recovered' or start a second incident.
    for second, valid in [(35, True), (40, False), (45, True), (50, True), (55, True)]:
        t = NOW + timedelta(seconds=second)
        state, events = transition(deepcopy(state), "SPY.US", None, quote(t) if valid else None, t)
        assert not events
    t = NOW + timedelta(seconds=60)
    state, events = transition(state, "SPY.US", None, quote(t), t)
    assert len(events) == 1 and "行情恢复" in events[0]["reason"]
    assert events[0]["quote_age_seconds"] == 0
    # Leaving and re-entering the monitoring window cannot manufacture a recovery.
    closed = NOW.replace(hour=21)
    state, events = transition(state, "SPY.US", None, None, closed)
    assert not events and state["data_monitor"] is None
    tomorrow = NOW + timedelta(days=1)
    state, events = transition(state, "SPY.US", None, quote(tomorrow), tomorrow)
    assert not events


def test_restart_gap_does_not_count_as_sustained_recovery():
    state = {
        "trading_date": NOW.date().isoformat(),
        "data_monitor": {
            "day": NOW.date().isoformat(),
            "alerted": True,
            "checked_at": NOW.isoformat(),
            "recovery_since": NOW.isoformat(),
        },
    }
    later = NOW + timedelta(minutes=10)
    state, events = transition(state, "SPY.US", None, quote(later), later)
    assert not events and state["data_monitor"]["alerted"]
    for second in (5, 10, 15):
        t = later + timedelta(seconds=second)
        state, events = transition(state, "SPY.US", None, quote(t), t)
        assert bool(events) == (second == 15)
    assert "行情恢复" in events[0]["reason"]
