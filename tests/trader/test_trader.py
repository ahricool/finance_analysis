"""Offline process boundaries, Redis revision cache, and lease safety."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from finance_analysis.integrations.market_data.realtime_state import keys
from finance_analysis.integrations.market_data.realtime_state.models import CandleState
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.market_stream.config import MarketStreamConfig
from finance_analysis.trader.market_cache import ConfirmedBarCache
from finance_analysis.trader.service import TraderService
from finance_analysis.trader.health import healthy
from tests.market_stream.fakes import FakeRedis, wait_until

SYMBOL = "AAPL.US"


def bar(stamp=None, close="10", confirmed=True):
    stamp = stamp or datetime(2026, 11, 25, 14, 30, tzinfo=timezone.utc)
    return CandleState(
        symbol=SYMBOL, bar_time=stamp, open=Decimal("10"), high=Decimal("12"),
        low=Decimal("9"), close=Decimal(close), volume=10, turnover=Decimal("100"),
        trade_session="Intraday", confirmed=confirmed, received_at=stamp+timedelta(minutes=1),
    )


@pytest.mark.asyncio
async def test_trader_reads_confirmed_candles_by_revision_and_sees_corrections():
    redis = FakeRedis()
    writer = RealtimeStateRepository(redis)
    reader = RealtimeStateRepository(redis)
    reader.get_confirmed_bar_snapshots = AsyncMock(wraps=reader.get_confirmed_bar_snapshots)
    cache = ConfirmedBarCache(reader)
    first = bar()
    await writer.upsert_bars(SYMBOL, [first])
    version = await redis.get(keys.bars_revision_key(SYMBOL))
    assert version
    result = await cache.refresh([SYMBOL])
    assert len(result[SYMBOL]) == 1 and result[SYMBOL][0].close == Decimal("10")
    # A forming candle never advances the confirmed revision.
    await writer.write_current_candle(bar(first.bar_time+timedelta(minutes=1), confirmed=False))
    await cache.refresh([SYMBOL])
    assert await redis.get(keys.bars_revision_key(SYMBOL)) == version
    assert reader.get_confirmed_bar_snapshots.await_args.args[0] == []
    corrected = replace(first, close=Decimal("11"), received_at=first.received_at+timedelta(seconds=2))
    await writer.upsert_bars(SYMBOL, [corrected])
    assert (await cache.refresh([SYMBOL]))[SYMBOL][0].close == Decimal("11")
    assert result[SYMBOL][0].close == Decimal("10")  # Previously scheduled round remains stable.
    await writer.clear_intraday(SYMBOL)
    assert (await cache.refresh([SYMBOL]))[SYMBOL] == ()
    assert await redis.get(keys.bars_revision_key(SYMBOL)) is None


@pytest.mark.asyncio
async def test_cache_legacy_fallback_expiry_and_read_failure(monkeypatch):
    redis = FakeRedis()
    repo = RealtimeStateRepository(redis)
    await repo.upsert_bars(SYMBOL, [bar()])
    await redis.delete(keys.bars_revision_key(SYMBOL))
    cache = ConfirmedBarCache(repo, reconcile_seconds=1)
    from finance_analysis.trader import market_cache
    clock = [1.0]
    monkeypatch.setattr(market_cache.time, "monotonic", lambda: clock[0])
    assert len((await cache.refresh([SYMBOL]))[SYMBOL]) == 1
    await redis.delete(keys.bars_data_key(SYMBOL), keys.bars_index_key(SYMBOL))
    clock[0] = 3
    assert (await cache.refresh([SYMBOL]))[SYMBOL] == ()
    repo.get_bar_revisions = AsyncMock(side_effect=RuntimeError("redis unavailable"))
    with pytest.raises(RuntimeError):
        await cache.refresh([SYMBOL])
    assert not cache.snapshots and not cache.revisions


@pytest.mark.asyncio
async def test_trader_owns_independent_lease_and_stops_exchange_modules(monkeypatch):
    from finance_analysis.database.session import DatabaseManager
    monkeypatch.setattr(DatabaseManager, "get_instance", lambda: None)
    redis = FakeRedis()
    repo = RealtimeStateRepository(redis)
    service = TraderService(config=MarketStreamConfig(redis_url="redis://fake", heartbeat_seconds=1), repository=repo)
    await redis.set(keys.LEADER_LOCK_KEY, "market", ex=30)
    await repo.write_heartbeat({"trading_owner": "trader"})
    started, stopped = set(), set()

    async def options():
        started.add("options")
        await service.stop_event.wait()
        stopped.add("options")

    async def exchange(name):
        started.add(name)
        try:
            await asyncio.Event().wait()
        finally:
            stopped.add(name)

    monkeypatch.setattr(service, "_run_options", options)
    monkeypatch.setattr(service, "_run_paper", lambda: exchange("paper"))
    monkeypatch.setattr(service, "_run_live", lambda: exchange("live"))
    task = asyncio.create_task(service.run())
    await wait_until(lambda: keys.TRADER_HEARTBEAT_KEY in redis.hashes and len(started) == 3)
    assert await redis.get(keys.LEADER_LOCK_KEY) == "market"
    assert await redis.get(keys.TRADER_LEADER_LOCK_KEY) == service.leader.token
    assert redis.hashes[keys.TRADER_HEARTBEAT_KEY]["lease_token"] == service.leader.token
    second = TraderService(config=service.config, repository=RealtimeStateRepository(redis))
    assert not await second.run()
    service.request_stop()
    assert await asyncio.wait_for(task, timeout=1)
    assert stopped == started
    assert await redis.get(keys.TRADER_LEADER_LOCK_KEY) is None
    assert await redis.get(keys.LEADER_LOCK_KEY) == "market"


@pytest.mark.asyncio
async def test_legacy_streamer_blocks_new_trader_until_handoff(monkeypatch):
    redis = FakeRedis()
    repo = RealtimeStateRepository(redis)
    service = TraderService(config=MarketStreamConfig(redis_url="redis://fake"), repository=repo)
    await redis.set(keys.LEADER_LOCK_KEY, "legacy", ex=30)
    await repo.write_heartbeat({"status": "READY"})
    assert await service._legacy_streamer_present()
    async def upgrade(_):
        await repo.write_heartbeat({"status": "READY", "trading_owner": "trader"})
    monkeypatch.setattr(service, "_pause", upgrade)
    assert await service._wait_compatible_streamer()
    assert not await service._legacy_streamer_present()
    await redis.delete(keys.STREAMER_HEARTBEAT_KEY)
    assert await service._legacy_streamer_present()  # conservative startup
    assert not await service._legacy_streamer_present(require_heartbeat=False)  # running trader tolerates restart


@pytest.mark.asyncio
async def test_trader_stops_on_lease_loss(monkeypatch):
    redis = FakeRedis()
    service = TraderService(
        config=MarketStreamConfig(redis_url="redis://fake"), repository=RealtimeStateRepository(redis),
    )
    assert await service.leader.acquire()
    await redis.set(keys.TRADER_LEADER_LOCK_KEY, "other")
    monkeypatch.setattr(service, "_pause", AsyncMock())
    await service._renew()
    assert service.failed and service.stop_event.is_set()


def test_health_requires_own_host_and_matching_lease():
    redis = Mock()
    redis.hgetall.return_value = {"status": "READY", "instance_id": "trader:1:abc", "lease_token": "owner"}
    redis.get.return_value = "owner"
    redis.ttl.return_value = 25
    assert healthy(redis, "trader")
    assert not healthy(redis, "other")
    redis.get.return_value = "new-owner"
    assert not healthy(redis, "trader")


@pytest.mark.asyncio
async def test_options_scheduler_reads_redis_market_cache_without_streamer_memory(monkeypatch):
    from finance_analysis.intraday_options import scheduler
    from finance_analysis.integrations.market_data.realtime_state.models import QuoteState

    redis = FakeRedis()
    repo = RealtimeStateRepository(redis)
    stamp = datetime(2026, 11, 25, 14, 30, tzinfo=timezone.utc)
    now = stamp + timedelta(minutes=15, seconds=20)
    await repo.upsert_bars(SYMBOL, [bar(stamp + timedelta(minutes=i)) for i in range(15)])
    await repo.write_quote(QuoteState(
        symbol=SYMBOL, last_price=Decimal("10"), event_time=now, received_at=now,
        trading_date=now.date(), timestamp_kind="exchange",
    ))
    monkeypatch.setattr(scheduler, "SYMBOLS", (SYMBOL,))
    monkeypatch.setattr(scheduler, "open_retired_symbols", lambda: set())
    monkeypatch.setattr(scheduler, "load_daily_context", lambda *_: {})
    monkeypatch.setattr(scheduler, "utc_now", lambda: now)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    calls = []

    def process(symbol, result, quote, stamp):
        calls.append((symbol, quote, stamp))
        loop.call_soon_threadsafe(stop.set)
        return {}

    monkeypatch.setattr(scheduler, "process", process)
    cache = ConfirmedBarCache(repo)
    await asyncio.wait_for(scheduler.run(repo, {}, stop, bar_source=cache), timeout=3)
    assert calls[0][0] == SYMBOL and calls[0][1].last_price == Decimal("10")
    assert len(cache.snapshots[SYMBOL]) == 15


@pytest.mark.asyncio
async def test_optional_module_return_and_failure_do_not_stop_trader(monkeypatch):
    service = TraderService(
        config=MarketStreamConfig(redis_url="redis://fake"), repository=RealtimeStateRepository(FakeRedis()),
    )
    factory = AsyncMock(side_effect=[RuntimeError("temporary"), None])
    monkeypatch.setattr(service, "_pause", AsyncMock())
    await service._supervise("paper_trade", factory)
    assert factory.await_count == 2
    assert service.statuses["paper_trade"] == "INACTIVE"
    assert not service.stop_event.is_set()


@pytest.mark.asyncio
async def test_confirmed_snapshot_excludes_unindexed_hash_data():
    from finance_analysis.integrations.market_data.realtime_state.repository import _candle_json
    redis = FakeRedis()
    repo = RealtimeStateRepository(redis)
    first = bar()
    await repo.upsert_bars(SYMBOL, [first])
    stray = bar(first.bar_time+timedelta(minutes=1), close="11")
    await redis.hset(keys.bars_data_key(SYMBOL), str(int(stray.bar_time.timestamp())), _candle_json(stray))
    revision, rows = (await repo.get_confirmed_bar_snapshots([SYMBOL]))[SYMBOL]
    assert revision and [row.bar_time for row in rows] == [first.bar_time]
