from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finance_analysis.integrations.market_data.realtime_state.models import CandleState
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.market_stream.config import (
    latest_completed_bar_time,
    market_timezone,
    market_trading_date,
)
from finance_analysis.market_stream.config import MarketStreamConfig
from finance_analysis.market_stream.service import MarketStreamService
from finance_analysis.market_stream.symbol_state import SymbolRuntimeState, SymbolStatus
from finance_analysis.market_stream.warmup import LongbridgeHistoryLoader
from tests.market_stream.fakes import FakeRedis, FakeStreamingClient


def candle(symbol: str, bar_time: datetime) -> CandleState:
    return CandleState(
        symbol=symbol,
        bar_time=bar_time,
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10"),
        volume=1,
        turnover=None,
        trade_session="Intraday",
        confirmed=True,
        received_at=bar_time + timedelta(seconds=1),
    )


def app() -> MarketStreamService:
    return MarketStreamService(
        config=MarketStreamConfig(redis_url="redis://fake"),
        repository=RealtimeStateRepository(FakeRedis()),
        client_factory=FakeStreamingClient,
    )


def test_market_timezones_use_iana_zoneinfo() -> None:
    assert market_timezone("CN").key == "Asia/Shanghai"
    assert market_timezone("HK").key == "Asia/Hong_Kong"
    assert market_timezone("US").key == "America/New_York"


def test_runtime_numeric_settings_are_not_read_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("REALTIME_REDIS_URL", "redis://configured/0")
    monkeypatch.setenv("MARKET_STREAM_WATCHLIST_POLL_SECONDS", "999")
    monkeypatch.setenv("MARKET_STREAM_BAR_LIMIT", "999")
    config = MarketStreamConfig.from_env()
    assert config.redis_url == "redis://configured/0"
    assert config.watchlist_poll_seconds == 5
    assert config.bar_limit == 420


def test_subscription_ttl_must_exceed_two_heartbeats() -> None:
    with pytest.raises(ValueError, match="must exceed"):
        MarketStreamConfig(
            redis_url="redis://fake",
            heartbeat_seconds=5,
            subscription_state_ttl_seconds=10,
        )


def test_same_utc_time_maps_to_each_market_trading_date() -> None:
    value = datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)
    assert market_trading_date(value, "CN").isoformat() == "2026-01-01"
    assert market_trading_date(value, "HK").isoformat() == "2026-01-01"
    assert market_trading_date(value, "US").isoformat() == "2025-12-31"


def test_us_dst_and_winter_offsets_are_not_fixed() -> None:
    summer = datetime(2026, 7, 1, 12, tzinfo=timezone.utc).astimezone(market_timezone("US"))
    winter = datetime(2026, 1, 1, 12, tzinfo=timezone.utc).astimezone(market_timezone("US"))
    assert summer.utcoffset() == timedelta(hours=-4)
    assert winter.utcoffset() == timedelta(hours=-5)


def test_utc_cross_day_does_not_force_us_local_cross_day() -> None:
    before = datetime(2026, 7, 2, 0, 30, tzinfo=timezone.utc)
    after = before + timedelta(hours=2)
    assert market_trading_date(before, "US") == market_trading_date(after, "US")


def test_cn_and_hk_lunch_recess_use_last_morning_completed_minute() -> None:
    cn_lunch = datetime(2026, 6, 26, 12, 30, tzinfo=market_timezone("CN"))
    hk_lunch = datetime(2026, 6, 26, 12, 30, tzinfo=market_timezone("HK"))
    cn_latest = latest_completed_bar_time(cn_lunch, "CN")
    hk_latest = latest_completed_bar_time(hk_lunch, "HK")
    assert cn_latest is not None and cn_latest.astimezone(market_timezone("CN")).strftime("%H:%M") == "11:29"
    assert hk_latest is not None and hk_latest.astimezone(market_timezone("HK")).strftime("%H:%M") == "11:59"


def test_cn_and_hk_lunch_are_not_treated_as_cache_gaps() -> None:
    service = app()
    cn_now = datetime(2026, 6, 26, 12, 30, tzinfo=market_timezone("CN"))
    hk_now = datetime(2026, 6, 26, 12, 30, tzinfo=market_timezone("HK"))
    cn_end = latest_completed_bar_time(cn_now, "CN")
    hk_end = latest_completed_bar_time(hk_now, "HK")
    assert cn_end is not None and hk_end is not None
    cn_bars = [candle("600519.SH", cn_end - timedelta(minutes=index)) for index in range(15)]
    hk_bars = [candle("0700.HK", hk_end - timedelta(minutes=index)) for index in range(15)]
    assert service._cache_has_current_session(cn_bars, "CN", now=cn_now)
    assert service._cache_has_current_session(hk_bars, "HK", now=hk_now)


def test_market_local_cross_day_clears_old_in_memory_bars() -> None:
    service = app()
    state = SymbolRuntimeState(
        symbol="600519.SH",
        market_type="CN",
        status=SymbolStatus.ACTIVE,
    )
    first = candle("600519.SH", datetime(2026, 6, 25, 1, 30, tzinfo=timezone.utc))
    second = candle("600519.SH", datetime(2026, 6, 26, 1, 30, tzinfo=timezone.utc))
    service._update_live_candle_memory(first, state)
    service._update_live_candle_memory(second, state)
    assert list(service.bars_1m["600519.SH"]) == [second]
    assert state.trading_date.isoformat() == "2026-06-26"


@pytest.mark.asyncio
async def test_history_loader_filters_by_target_market_latest_trading_date() -> None:
    class Fetcher:
        def get_minute_candlesticks(self, symbol, interval, count, include_extended):
            return [
                {
                    "timestamp": "2026-06-25T01:30:00+00:00",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10,
                    "volume": 1,
                    "turnover": 10,
                    "trade_session": "Intraday",
                },
                {
                    "timestamp": "2026-06-26T01:30:00+00:00",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10,
                    "volume": 1,
                    "turnover": 10,
                    "trade_session": "Intraday",
                },
            ]

    bars = await LongbridgeHistoryLoader(Fetcher()).fetch("600519.SH", "CN", 420)
    assert len(bars) == 1
    assert market_trading_date(bars[0].bar_time, "CN").isoformat() == "2026-06-26"
    assert bars[0].bar_time.tzinfo is not None
