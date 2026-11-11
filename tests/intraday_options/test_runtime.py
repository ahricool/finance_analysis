import asyncio
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from finance_analysis.integrations.market_data.realtime_state.models import QuoteState
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.interfaces.api.v1.schemas.intraday_options import IntradayOptionsResponse
from finance_analysis.intraday_options.config import SYMBOLS
from finance_analysis.intraday_options.runtime import Publisher, data_status, read_snapshot, result_key, session_context
from finance_analysis.intraday_options.scoring import calculate
from finance_analysis.market_stream.watchlist_monitor import load_stream_targets
from tests.intraday_options.test_scoring import START, candles
from tests.market_stream.fakes import FakeRedis


def test_publisher_and_read_only_snapshot_latest_cache_only():
    async def run():
        repo = RealtimeStateRepository(FakeRedis())
        publisher = Publisher(repo)
        bars = candles([0.0004] * 60)
        now = START + timedelta(minutes=60, seconds=5)
        await publisher.publish("SPY.US", bars, now)
        original = await repo.redis.get(result_key("SPY.US"))
        await publisher.publish("SPY.US", candles([0.0004] * 60), now)
        assert await repo.redis.get(result_key("SPY.US")) == original
        await repo.write_quote(
            QuoteState(
                "SPY.US",
                trading_date=START.date(),
                last_price=Decimal("99"),
                pre_close=Decimal("100"),
                event_time=now,
                received_at=now,
            )
        )
        result = await read_snapshot(repo, {"SPY.US": "标普500ETF"}, now)
        parsed = IntradayOptionsResponse.model_validate(result)
        assert len(parsed.items) == 30
        row = parsed.items[0]
        assert row.symbol == "SPY.US" and row.data_status == "ready"
        assert row.result.direction == "bullish" and row.change_pct < 0  # day return never sets direction
        assert parsed.items[7].symbol == "SPCX.US" and parsed.items[7].issues
        assert parsed.items[7].result is None
        assert len([k for k in repo.redis.strings if k.startswith("rt:intraday-options")]) == 1
        delayed = await read_snapshot(repo, {}, now + timedelta(minutes=2))
        assert delayed["items"][0]["data_status"] == "delayed"
        assert delayed["items"][0]["result"]["score"] == row.result.score
        assert delayed["items"][0]["result"]["as_of"] == row.result.as_of.isoformat()
        assert delayed["items"][0]["quote_status"] == "delayed"
        # New session must not expose yesterday's score or quote as current.
        tomorrow = await read_snapshot(repo, {}, START + timedelta(days=1, minutes=1))
        assert tomorrow["items"][0]["result"] is None
        assert tomorrow["items"][0]["last_price"] is None

    asyncio.run(run())


def test_session_boundaries_and_closed_results():
    bars = candles([0.0002] * 390)
    close = START + timedelta(minutes=390)
    result = calculate("SPY.US", bars, close)
    assert data_status(result, close + timedelta(hours=4), START.date(), "closed") == "ready"
    assert data_status(result, close - timedelta(minutes=1), START.date(), "open") == "invalid_time"
    preopen = START - timedelta(minutes=1)
    day, status = session_context(preopen)
    assert status == "preopen" and day < START.date()
    day, status = session_context(START)
    assert day == START.date() and status == "open"


def test_fixed_pool_is_added_without_modifying_personal_watchlists(monkeypatch):
    from finance_analysis.market_stream import watchlist_monitor

    monkeypatch.setattr(watchlist_monitor, "load_watchlist_targets", lambda: {"KO.US": SimpleNamespace(symbol="KO.US")})
    values = load_stream_targets()
    assert len(values) == 31 and set(SYMBOLS).issubset(values)
    assert values["SPCX.US"].symbol == "SPCX.US"


def test_latest_minute_grace_and_afterhours_do_not_refresh_score():
    async def run():
        repo = RealtimeStateRepository(FakeRedis())
        publisher = Publisher(repo)
        bars = candles([0.0002] * 390)
        close = START + timedelta(minutes=390)
        await publisher.publish("SPY.US", bars, close)
        first = await repo.redis.get(result_key("SPY.US"))
        await publisher.publish("SPY.US", bars + candles([0.01] * 20, start=close), close + timedelta(minutes=20))
        assert await repo.redis.get(result_key("SPY.US")) == first
        await publisher.publish("SPY.US", bars[:60], close)
        assert await repo.redis.get(result_key("SPY.US")) == first
        current = calculate("SPY.US", bars[:60], START + timedelta(minutes=60))
        assert data_status(current, START + timedelta(minutes=61, seconds=14), START.date(), "open") == "ready"
        assert data_status(current, START + timedelta(minutes=61, seconds=16), START.date(), "open") == "delayed"

    asyncio.run(run())
