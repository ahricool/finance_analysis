import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from finance_analysis.intraday_options import opportunity_alert
from finance_analysis.intraday_options.runtime import Publisher, read_snapshot
from finance_analysis.intraday_options.rules import policy
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from tests.intraday_options.test_scoring import START
from tests.intraday_options.test_simulation import quote
from tests.intraday_options.test_structure import oscillation, prices
from tests.market_stream.fakes import FakeRedis


@pytest.mark.parametrize("session,offset", [("pre", -180), ("post", 400), ("overnight", 800)])
def test_confirmed_rolling_shape_visible_outside_regular_hours(session, offset):
    async def check():
        shift = timedelta(minutes=offset)
        bars = [replace(b, trade_session=session, bar_time=b.bar_time + shift, received_at=b.received_at + shift)
                for b in prices(oscillation() + [101.3, 101.4])]
        now = bars[-1].bar_time + timedelta(minutes=1, seconds=2)
        repo = RealtimeStateRepository(FakeRedis())
        await Publisher(repo).publish("SPY.US", bars, now)
        await repo.write_quote(replace(quote(now, 101.4), trade_session=session))
        row = (await read_snapshot(repo, {}, now, symbols=["SPY.US"]))["items"][0]
        assert row["data_status"] == "ready" and row["result"]["state"]
        assert row["simulation"] is None and row["opportunity_eligible"]
        assert row["ranked_opportunity"]["kind"] in {"box_breakout", "midday_wave_breakout", "pivot_breakout"}
        assert "opening_breakout" not in {b["kind"] for b in row["result"]["opportunities"]["branches"]}

    asyncio.run(check())


def test_rolling_policy_and_alert_retry_dedup(monkeypatch):
    monkeypatch.setenv("INTRADAY_OPENING_MIN_EFFICIENCY", "invalid-retired-setting")
    policy.cache_clear()
    cfg = policy()
    assert all((cfg.pivot_enabled, cfg.midday_wave_enabled, cfg.box_enabled, cfg.continuation_enabled, cfg.recovery_enabled))
    assert not cfg.opening_enabled
    service = Mock()
    service.send.side_effect = [SimpleNamespace(notification_id=None), SimpleNamespace(notification_id=1)]
    monkeypatch.setattr(opportunity_alert, "get_notification_service", lambda: service)

    async def check():
        redis = FakeRedis()
        branch = dict(kind="box_breakout", structure_id="box:1", direction="bullish", started_at=START.isoformat(),
                      breakout_alert_score=95, quality_score=85, trigger=100, invalidation=99,
                      confirmed_at=START.isoformat(), expires_at=(START + timedelta(minutes=5)).isoformat())
        async def send(when, quote_at):
            await opportunity_alert.alert_opportunity(redis, "SPY.US", branch, START, quote_at, when)
        await send(START + timedelta(minutes=2), START)
        assert not service.send.called
        await send(START, START)
        await asyncio.gather(send(START, START), send(START, START))
        assert service.send.call_count == 2
        assert "短线机会" in service.send.call_args.kwargs["title"]

    asyncio.run(check())


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("tail,expected", [
    ([101.29, 101.30, 101.46, 101.7, 101.72], [None, None, "守位续推", "已延伸", None]),
    ([101.47, 101.49, 101.75], ["强突破", None, "已延伸"]),
    ([101.70, 101.72], ["已延伸", None]),
    ([101.29, 101.24, 101.42], [None, None, None]),
])
def test_pivot_alerts_replay_closed_bars_on_both_feeds(side, tail, expected):
    from finance_analysis.contracts.analysis import summarize
    from finance_analysis.intraday_options.opportunities import calculate_opportunities

    background = [100] * 48 + [100 + .08 * i for i in range(16)] + [101.1, 101.03, 101.08]
    background[40] = 101.2
    bars = prices([100 + side * (v - 100) for v in background + tail])
    bars = [replace(b, volume=3000) if i >= len(background) else b for i, b in enumerate(bars)]
    for n, reason in enumerate(expected, len(background) + 1):
        window = bars[:n]
        opportunities = calculate_opportunities(window)
        equity = opportunity_alert.alert_candidates(opportunities)
        rows = [dict(timestamp=int(b.bar_time.timestamp() * 1000), closed=True, open=b.open, high=b.high,
                     low=b.low, close=b.close, volume=b.volume, turnover=b.turnover or 0) for b in window]
        summary = summarize("TESTUSDT", rows, rows[-1]["timestamp"] + 60_000, include_alerts=True)
        if n == len(background) + 1 and reason is None:
            assert opportunities["primary"]["kind"] == summary["opportunity"]["kind"] == "pivot_breakout"
        for candidates in (equity, summary["alerts"]):
            actual = ["已延伸" if b["status"] == "extended" else b["breakout_alert_reason"]
                      for b in candidates if b["kind"] == "pivot_breakout"]
            assert actual == ([reason] if reason else [])


def test_extended_notification_claim_is_independent_and_shared_by_concurrent_senders(monkeypatch):
    service = Mock()
    service.send.return_value = SimpleNamespace(notification_id=1)
    monkeypatch.setattr(opportunity_alert, "get_notification_service", lambda: service)

    async def check():
        redis = FakeRedis()
        branch = dict(kind="pivot_breakout", structure_id="same", direction="bullish", started_at=START.isoformat(),
                      breakout_alert_score=95, quality_score=85,
                      trigger=100, invalidation=99, confirmed_at=START.isoformat(),
                      expires_at=(START + timedelta(minutes=5)).isoformat(), breakout_alert_reason="强突破",
                      breakout_alert_context=dict(hour_edge=100, distance_atr=1.5, volume_ratio=3.2))
        for status in ("confirmed", "extended", "extended"):
            if status == "extended":
                branch.update(kind="box_breakout", structure_id="another-shape")
            branch["status"] = status
            await asyncio.gather(*(opportunity_alert.alert_opportunity(redis, "S", branch, START, START, START)
                                   for _ in range(2)))
        assert [c.kwargs["title"].split(" · ")[-1] for c in service.send.call_args_list] == ["强突破", "已延伸"]
        branch.update(kind="pivot_breakout", structure_id="same")
        await opportunity_alert.alert_opportunity(redis, "S", branch, START, START, START)
        assert service.send.call_count == 2
        await opportunity_alert.alert_opportunity(redis, "OTHER", branch, START, START, START)
        branch["status"] = "confirmed"
        await opportunity_alert.alert_opportunity(redis, "OTHER", branch, START, START, START)
        assert service.send.call_count == 3
        assert "3.2 倍" in service.send.call_args.args[0]

    asyncio.run(check())


@pytest.mark.parametrize("defect", [
    "low_volume", "wick", "inside_hour", "gap", "sampled", "short_history", "lost_level", "single_test", "ordinary_volume",
])
def test_extended_breakout_requires_complete_high_quality_evidence(defect):
    from decimal import Decimal
    from finance_analysis.intraday_options.opportunities import calculate_opportunities

    values = [100] * 48 + [100 + .08 * i for i in range(16)] + [101.1, 101.03, 101.08, 101.7]
    values[40] = 101.2
    bars = prices(values)
    bars[-1] = replace(bars[-1], volume=3000)
    if defect == "low_volume":
        bars[-1] = replace(bars[-1], volume=1000)
    elif defect == "wick":
        bars[-1] = replace(bars[-1], high=Decimal("103"))
    elif defect == "inside_hour":
        bars[20] = replace(bars[20], high=Decimal("102"))
    elif defect == "gap":
        bars.pop(20)
    elif defect == "sampled":
        bars[20] = replace(bars[20], sampled=True)
    elif defect == "short_history":
        bars = bars[20:]
    elif defect == "single_test":
        bars[40:42] = prices([100] * 42)[40:42]
    elif defect == "ordinary_volume":
        bars[19:22] = [replace(b, volume=2000) for b in bars[19:22]]
    else:
        bars = bars[:-1] + prices(values[:-1] + [101.47, 101.24, 101.72])[-3:]
        bars[-3:] = [replace(b, volume=10000) for b in bars[-3:]]
        assert opportunity_alert.alert_candidates(calculate_opportunities(bars[:-2]))
    opportunities = calculate_opportunities(bars)
    assert any(b["kind"] == "pivot_breakout" and b["status"] == "extended" for b in opportunities["branches"])
    assert not [b for b in opportunity_alert.alert_candidates(opportunities) if b["kind"] == "pivot_breakout"]


def test_same_direction_overlapping_breakout_alerts_select_highest_evidence():
    base = dict(status="extended", direction="bearish", extended_at="now", breakout_alert_at="now")
    branches = [dict(base, kind=kind, structure_id=kind, breakout_alert_score=score)
                for kind, score in [("pivot_breakout", 94.9), ("box_breakout", 96), ("midday_wave_breakout", 98)]]

    def evaluate(items):
        return opportunity_alert.alert_candidates(dict(reference=False, as_of="now", branches=items))

    assert evaluate(branches) == [branches[-1]]
    assert evaluate(branches[:1]) == []
