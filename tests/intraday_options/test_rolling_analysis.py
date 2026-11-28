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
        branch = dict(kind="box_breakout", structure_id="box:1", direction="bullish", quality_score=85, trigger=100, invalidation=99,
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
