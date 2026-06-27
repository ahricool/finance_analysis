from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from finance_analysis.integrations.market_data.realtime_state import keys
from finance_analysis.integrations.market_data.realtime_state.models import QuoteState
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.market_stream.config import MarketStreamConfig
from finance_analysis.market_stream.leader_lock import LeaderLock
from finance_analysis.market_stream.service import MarketStreamService
from finance_analysis.market_stream.symbol_state import SubscriptionTarget, SymbolRuntimeState, SymbolStatus
from finance_analysis.market_stream.watchlist_monitor import WatchListMonitor
from tests.market_stream.fakes import FakeRedis, FakeStreamingClient, wait_until


@pytest.mark.asyncio
async def test_leader_lock_prevents_second_instance_and_checks_token() -> None:
    redis = FakeRedis()
    first = LeaderLock(redis, ttl_seconds=30)
    second = LeaderLock(redis, ttl_seconds=30)
    assert await first.acquire()
    assert not await second.acquire()
    assert await first.renew()
    redis.strings[keys.LEADER_LOCK_KEY] = "another-token"
    assert not await first.renew()
    assert not await first.release()


@pytest.mark.asyncio
async def test_service_request_stop_is_graceful_and_heartbeat_has_ttl() -> None:
    FakeStreamingClient.instances.clear()
    redis = FakeRedis()
    repo = RealtimeStateRepository(redis)

    class History:
        async def fetch(self, symbol, market_type, count):
            return []

    config = MarketStreamConfig(
        redis_url="redis://fake",
        watchlist_poll_seconds=1,
        heartbeat_seconds=1,
        leader_lock_ttl_seconds=30,
        redis_flush_interval_ms=100,
        bar_limit=420,
    )
    service = MarketStreamService(
        config=config,
        repository=repo,
        watchlist_monitor=WatchListMonitor(
            lambda: {"AAPL.US": SubscriptionTarget("AAPL.US", "US")}
        ),
        client_factory=FakeStreamingClient,
        history_loader=History(),
    )
    task = asyncio.create_task(service.run())
    await wait_until(lambda: bool(FakeStreamingClient.instances))
    await wait_until(lambda: keys.STREAMER_HEARTBEAT_KEY in redis.hashes)
    service.request_stop()
    assert await asyncio.wait_for(task, timeout=1)
    assert FakeStreamingClient.instances[0].closed
    assert redis.closed
    assert await redis.ttl(keys.STREAMER_HEARTBEAT_KEY) == 30


@pytest.mark.asyncio
async def test_heartbeat_refreshes_subscription_ttls_in_one_pipeline_for_200_symbols() -> None:
    redis = FakeRedis()
    service = MarketStreamService(
        config=MarketStreamConfig(redis_url="redis://fake", heartbeat_seconds=1),
        repository=RealtimeStateRepository(redis),
        client_factory=FakeStreamingClient,
    )
    for index in range(200):
        symbol = f"S{index}.US"
        service.manager.symbol_states[symbol] = SymbolRuntimeState(
            symbol=symbol,
            market_type="US",
            status=SymbolStatus.ACTIVE,
        )
        redis.hashes[keys.subscription_key(symbol)]["status"] = "ACTIVE"
        redis.expires[keys.subscription_key(symbol)] = 1
    before = redis.pipeline_executes
    task = asyncio.create_task(service._heartbeat())
    await asyncio.sleep(0.02)
    service.request_stop()
    await asyncio.wait_for(task, timeout=1.2)

    assert redis.pipeline_executes - before == 2
    assert all(
        redis.expires[keys.subscription_key(f"S{index}.US")] == 60
        for index in range(200)
    )


@pytest.mark.asyncio
async def test_subscription_state_persists_market_and_trading_date_with_ttl() -> None:
    redis = FakeRedis()
    service = MarketStreamService(
        config=MarketStreamConfig(redis_url="redis://fake"),
        repository=RealtimeStateRepository(redis),
        client_factory=FakeStreamingClient,
    )
    state = SymbolRuntimeState(
        symbol="600519.SH",
        market_type="CN",
        trading_date=date(2026, 6, 26),
        status=SymbolStatus.ACTIVE,
    )
    await service._write_symbol_state(state)
    stored = redis.hashes[keys.subscription_key("600519.SH")]
    assert stored["market_type"] == "CN"
    assert stored["trading_date"] == "2026-06-26"
    assert redis.expires[keys.subscription_key("600519.SH")] == 60


@pytest.mark.asyncio
async def test_inactive_subscription_is_not_renewed_and_expires() -> None:
    redis = FakeRedis()
    service = MarketStreamService(
        config=MarketStreamConfig(redis_url="redis://fake", heartbeat_seconds=1),
        repository=RealtimeStateRepository(redis),
        client_factory=FakeStreamingClient,
    )
    symbol = "AAPL.US"
    service.manager.symbol_states[symbol] = SymbolRuntimeState(
        symbol=symbol,
        market_type="US",
        status=SymbolStatus.INACTIVE,
    )
    redis.hashes[keys.subscription_key(symbol)]["status"] = "INACTIVE"
    redis.expires[keys.subscription_key(symbol)] = 1
    task = asyncio.create_task(service._heartbeat())
    await asyncio.sleep(0.02)
    service.request_stop()
    await asyncio.wait_for(task, timeout=1.2)
    assert redis.expires[keys.subscription_key(symbol)] == 1
    redis.advance(2)
    assert keys.subscription_key(symbol) not in redis.hashes


@pytest.mark.asyncio
async def test_redis_flush_failure_is_retried_without_stopping_service() -> None:
    redis = FakeRedis()
    service = MarketStreamService(
        config=MarketStreamConfig(redis_url="redis://fake", redis_flush_interval_ms=100),
        repository=RealtimeStateRepository(redis),
        client_factory=FakeStreamingClient,
    )
    now = datetime.now(timezone.utc)
    service.pending_quotes["AAPL.US"] = QuoteState(
        symbol="AAPL.US", last_price=Decimal("1"), event_time=now, received_at=now
    )
    redis.fail_execute = True
    task = asyncio.create_task(service._flush_redis())
    await asyncio.sleep(0.12)
    assert service.redis_degraded
    assert "AAPL.US" in service.pending_quotes
    assert not service.stop_event.is_set()
    await asyncio.sleep(0.12)
    assert "AAPL.US" not in service.pending_quotes
    service.request_stop()
    await asyncio.wait_for(task, timeout=0.5)
