"""PR #526 review execution-hygiene regressions (quote floors, monitoring, upgrades, monotonic ticks)."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from finance_analysis.intraday_options.simulation import transition
from finance_analysis.intraday_options.structure import pool_rank_context
from tests.intraday_options.test_scoring import START, candles
from tests.intraday_options.test_simulation import NOW, quote, result


def test_invalid_peer_revision_updates_rank_evidence_floor():
    left = candles([0, 0, .03], symbol="NVDA.US")
    rival = candles([0, 0, .05], symbol="AMD.US")
    at = rival[-1].received_at + timedelta(seconds=8)
    peer = {"NVDA.US": left, "AMD.US": rival}
    prior = pool_rank_context("NVDA.US", left, peer, START, START.date(), min_peers=2)
    assert prior["long_rank"] == 2
    peer["AMD.US"] = [*rival[:-1], replace(rival[-1], high=Decimal(0), received_at=at)]
    updated = pool_rank_context("NVDA.US", left, peer, START, START.date(), min_peers=2)
    assert updated["long_rank"] == 1
    assert updated["evidence_at"] == at.isoformat()


def test_missing_quotes_alert_on_held_position_after_entry_cutoff():
    state, _ = transition(None, "SPY.US", result(), quote(), NOW)
    assert state["position"]
    # 12:00 NY (17:00 UTC) is well after V7's 10:00 NY entry cutoff, yet open position must stay monitored.
    noon = NOW.replace(hour=17, minute=0)
    collected = []
    for sec in range(0, 36, 5):
        state, events = transition(state, "SPY.US", None, None, noon + timedelta(seconds=sec))
        collected.extend(events)
    assert state["stopped"] and state["position"] and state["data_issue"]
    assert [e["kind"] for e in collected].count("data") == 1


def test_v4_intraday_upgrade_counts_already_consumed_entry():
    previous = {"trading_date": NOW.date().isoformat(), "used_processes": ["earlier-v4-trade"]}
    state, events = transition(previous, "SPY.US", result(), quote(), NOW)
    assert state["daily_entry_count"] == 1
    assert not state.get("position")
    assert not any(e["kind"] == "entry" for e in events)


def test_trailing_stop_waits_for_quote_after_structure_revision():
    state, _ = transition(None, "SPY.US", result(), quote(), NOW)
    state["position"].update(
        entry_price=100, invalidation=99, target=None, protection=101, peak_gain=5,
        protection_stage="trailing", protection_active=True,
    )
    close = NOW + timedelta(minutes=15)
    revision = close + timedelta(seconds=8)
    corrected = dict(
        trading_date=state["trading_date"], as_of=close.isoformat(),
        target_evidence_at=revision.isoformat(),
        recent_bars=[{"close_at": close.isoformat(), "low": 103.5, "high": 105}],
    )
    earlier = quote(close + timedelta(seconds=1), 103.2)
    held, events = transition(state, "SPY.US", corrected, earlier, close + timedelta(seconds=10))
    assert held["position"]["protection"] == 101
    assert not any(e["kind"] == "exit" for e in events)
    now = close + timedelta(seconds=11)
    held, _ = transition(held, "SPY.US", corrected, quote(now, 104), now)
    assert held["position"]["protection"] == 103.5
    held, _ = transition(held, "SPY.US", corrected, earlier, now + timedelta(seconds=1))
    assert held["position"]["last_price_at"] == now.isoformat()
    next_tick = now + timedelta(seconds=3)
    closed, events = transition(held, "SPY.US", corrected, quote(next_tick, 103.2), next_tick)
    assert closed["position"] is None and any(e["kind"] == "exit" for e in events)
