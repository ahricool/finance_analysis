"""Same-minute corrections must refresh latest-only scores, including after the close."""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.intraday_options import runtime
from finance_analysis.intraday_options.scoring import calculate
from tests.intraday_options.test_scoring import START, candles
from tests.market_stream.fakes import FakeRedis

CLOSE = START + timedelta(minutes=390)
SYMBOL = "SPY.US"


def setup_publisher(monkeypatch):
    repo = RealtimeStateRepository(FakeRedis())
    writes = AsyncMock(wraps=repo.redis.set)
    monkeypatch.setattr(repo.redis, "set", writes)
    computations = Mock(wraps=runtime.calculate)
    monkeypatch.setattr(runtime, "calculate", computations)
    return runtime.Publisher(repo), repo, writes, computations


async def cached(repo):
    return json.loads(await repo.redis.get(runtime.result_key(SYMBOL)))


def test_close_gap_repaired_by_reconnect_warmup_with_same_latest_time(monkeypatch):
    async def run():
        publisher, repo, writes, computations = setup_publisher(monkeypatch)
        complete = candles([0.0004] * 390)
        missing = complete[:380] + complete[381:]
        await publisher.publish(SYMBOL, missing, CLOSE)
        first = await cached(repo)
        assert first["score"] is not None
        assert all(w["data_status"] == "gap" for w in first["windows"])
        # Reconnection replaces objects and receipt timestamps, and fills the missing bar.
        recovery_time = CLOSE + timedelta(minutes=5)
        restored = [replace(b, received_at=recovery_time) for b in complete]
        await publisher.publish(SYMBOL, restored, recovery_time)
        result = await cached(repo)
        assert result["as_of"] == first["as_of"]
        assert all(w["data_status"] == "ready" for w in result["windows"])
        assert result["score"] == 100
        assert result == calculate(SYMBOL, restored, recovery_time)
        assert writes.await_count == 2
        assert computations.call_count == 2

    asyncio.run(run())


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_closed_ohlc_revision_refreshes_same_minute_score(monkeypatch, field):
    async def run():
        publisher, repo, writes, _ = setup_publisher(monkeypatch)
        bars = candles([0.0004] * 390)
        await publisher.publish(SYMBOL, bars, CLOSE)
        first = await cached(repo)
        bar = bars[-15]  # includes the short window's starting open
        revised = {"open": bar.close, "close": bar.open, "high": bar.high * 2, "low": bar.low / 2}
        # Deliberately mutate the existing object; an identity-based signature would miss this.
        setattr(bar, field, revised[field])
        now = CLOSE + timedelta(minutes=2)
        await publisher.publish(SYMBOL, bars, now)
        result = await cached(repo)
        assert result["as_of"] == first["as_of"]
        assert result["windows"] != first["windows"]
        assert result == calculate(SYMBOL, bars, now)
        assert writes.await_count == 2

    asyncio.run(run())


@pytest.mark.parametrize("field,bad", [("partial", True), ("sampled", True), ("volume", -1)])
def test_quality_flag_repair_restores_complete_windows(monkeypatch, field, bad):
    async def run():
        publisher, repo, writes, _ = setup_publisher(monkeypatch)
        bars = candles([0.0004] * 390)
        broken = list(bars)
        broken[-5] = replace(bars[-5], **{field: bad})
        await publisher.publish(SYMBOL, broken, CLOSE)
        assert all(w["data_status"] == "gap" for w in (await cached(repo))["windows"])
        await publisher.publish(SYMBOL, bars, CLOSE + timedelta(minutes=1))
        assert (await cached(repo))["score"] == 100
        assert writes.await_count == 2

    asyncio.run(run())


def test_unchanged_reconnect_quote_preview_and_outside_window_updates_are_deduplicated(monkeypatch):
    async def run():
        publisher, repo, writes, computations = setup_publisher(monkeypatch)
        bars = candles([0.0004] * 390)
        await publisher.publish(SYMBOL, bars, CLOSE)
        first = await cached(repo)
        now = CLOSE + timedelta(minutes=10)
        await publisher.publish(SYMBOL, bars, now)
        # Equivalent warmup in reverse order, with fresh reception metadata and volume.
        restored = [replace(b, received_at=now, volume=2000, turnover=None, sample_count=99) for b in reversed(bars)]
        await publisher.publish(SYMBOL, restored, now)
        # Last forming candle is unrelated to the already closed regular-session input.
        preview = replace(bars[-1], high=bars[-1].high * 2, confirmed=False, received_at=now)
        afterhours = candles([0.01] * 10, start=CLOSE)
        await publisher.publish(SYMBOL, restored + [preview] + afterhours, now)
        restored[-1] = replace(restored[-1], close=restored[-1].open)  # 09:30, outside the latest 60m
        await publisher.publish(SYMBOL, restored, now)
        assert await cached(repo) == first
        assert writes.await_count == computations.call_count == 1

    asyncio.run(run())


def test_older_latest_cannot_overwrite_newer_even_with_changed_values(monkeypatch):
    async def run():
        publisher, repo, writes, computations = setup_publisher(monkeypatch)
        bars = candles([0.0004] * 390)
        await publisher.publish(SYMBOL, bars, CLOSE)
        first = await cached(repo)
        older = candles([-0.0004] * 389)
        await publisher.publish(SYMBOL, older, CLOSE + timedelta(minutes=10))
        assert await cached(repo) == first
        assert writes.await_count == computations.call_count == 1

    asyncio.run(run())


def test_failed_correction_write_remains_retryable(monkeypatch):
    async def run():
        publisher, repo, writes, _ = setup_publisher(monkeypatch)
        bars = candles([0.0004] * 390)
        await publisher.publish(SYMBOL, bars[:-5] + bars[-4:], CLOSE)
        first = await cached(repo)
        writes.side_effect = RuntimeError("Redis unavailable")
        with pytest.raises(RuntimeError, match="Redis unavailable"):
            await publisher.publish(SYMBOL, bars, CLOSE + timedelta(minutes=1))
        assert await cached(repo) == first
        writes.side_effect = None
        await publisher.publish(SYMBOL, bars, CLOSE + timedelta(minutes=2))
        assert (await cached(repo))["score"] == 100
        assert writes.await_count == 3

    asyncio.run(run())


def test_new_forming_regular_minute_does_not_publish_until_closed(monkeypatch):
    async def run():
        publisher, repo, writes, computations = setup_publisher(monkeypatch)
        bars = candles([0.0004] * 61)
        now = START + timedelta(minutes=60, seconds=30)
        await publisher.publish(SYMBOL, bars[:60], now)
        first = await cached(repo)
        preview = replace(bars[-1], confirmed=False)
        await publisher.publish(SYMBOL, bars[:60] + [preview], now)
        preview.high *= 2
        await publisher.publish(SYMBOL, bars[:60] + [preview], now)
        # Even a premature confirmed flag cannot admit a minute that has not ended.
        await publisher.publish(SYMBOL, bars, now)
        assert await cached(repo) == first
        assert writes.await_count == computations.call_count == 1
        await publisher.publish(SYMBOL, bars, START + timedelta(minutes=61))
        assert (await cached(repo))["as_of"] != first["as_of"]
        assert writes.await_count == computations.call_count == 2

    asyncio.run(run())
