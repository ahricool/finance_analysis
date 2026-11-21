from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import HTTPException, Response

from finance_analysis.integrations.market_data.realtime_state.models import CandleState
from finance_analysis.interfaces.api.v1.endpoints import market_data
from finance_analysis.minute_forecast import publisher
from finance_analysis.minute_forecast.cache import close_replay_key, forecast_key
from finance_analysis.minute_forecast.models import ForecastSnapshot
from finance_analysis.minute_forecast.publisher import ForecastPublisher
from finance_analysis.minute_forecast.windows import btc_window, millis, stock_close_window, stock_window

MINUTE = timedelta(minutes=1)
NY = ZoneInfo("America/New_York")
SHANGHAI = ZoneInfo("Asia/Shanghai")


def candles(symbol, start, count):
    return [CandleState(symbol, start + i * MINUTE, Decimal(10), Decimal(11), Decimal(9), Decimal(10), 100,
                        Decimal(1000), None, True, start + (i + 1) * MINUTE) for i in range(count)]


def binance_rows(now):
    minute = now.replace(second=0, microsecond=0)
    return [[millis(minute + offset * MINUTE), "10", "11", "9", "10", "100",
             millis(minute + (offset + 1) * MINUTE) - 1, "1000"] for offset in range(-30, 1)]


def test_candle_window_uses_only_confirmed_observations_and_actual_early_close():
    now = datetime(2026, 11, 27, 12, 58, 7, tzinfo=NY)
    bars = candles("QQQ.US", now.replace(second=0) - 35 * MINUTE, 36)
    bars[0].sampled = True
    bars[-1].confirmed = False
    value = stock_window("QQQ.US", "US", reversed(bars), now)
    assert value is not None
    assert len(value.bars) == 34 and value.bars[-1].timestamp == millis(now.replace(second=0) - MINUTE)
    assert value.targets == [millis(now.replace(second=0) + i * MINUTE) for i in range(2)]
    bars[-2].partial = True
    assert stock_window("QQQ.US", "US", bars, now) is None


def test_cn_forecast_ends_at_lunch_and_begins_with_a_completed_afternoon_candle():
    late = datetime(2026, 11, 20, 11, 28, tzinfo=SHANGHAI)
    morning = candles("600519.SH", late - 32 * MINUTE, 34)
    assert stock_window("600519.SH", "CN", morning, late).targets == [millis(late), millis(late + MINUTE)]
    afternoon = late.replace(hour=13, minute=0)
    assert stock_window("600519.SH", "CN", morning, afternoon) is None
    window = stock_window("600519.SH", "CN", morning + candles("600519.SH", afternoon, 1), afternoon + MINUTE)
    assert len(window.bars) == 35
    assert window.targets[-1] == millis(afternoon + 5 * MINUTE)


def test_close_replay_anchors_to_early_close_and_excludes_postmarket_candles():
    close = datetime(2026, 11, 27, 13, 0, tzinfo=NY)
    bars = candles("QQQ.US", close - 32 * MINUTE, 34)
    assert stock_window("QQQ.US", "US", bars, close) is None
    replay = stock_close_window("QQQ.US", "US", bars, close.date())
    assert replay is not None
    assert replay.bars[-1].timestamp == millis(close - MINUTE)
    assert replay.targets == [millis(close + i * MINUTE) for i in range(5)]
    bars[-3].confirmed = False
    assert stock_close_window("QQQ.US", "US", bars, close.date()) is None


@pytest.mark.asyncio
async def test_batches_keep_all_active_symbols_and_btc_independent(monkeypatch):
    now = datetime(2026, 11, 20, 15, 45, 6, tzinfo=timezone.utc)
    monkeypatch.setattr(publisher, "utc_now", lambda: now)
    redis = Mock(eval=AsyncMock())
    writer = ForecastPublisher(redis, "http://mps", "small")
    symbols = [f"STK{i}.US" for i in range(12)]
    inputs = {symbol: candles(symbol, now.replace(second=0) - 30 * MINUTE, 30) for symbol in symbols}
    inputs["REMOVED.US"] = inputs[symbols[0]]
    markets = dict.fromkeys(symbols, "US")
    binance = Mock(spot_minute_rows=AsyncMock(return_value=binance_rows(now)))
    posted = []

    async def predict(request):
        import json

        batch = json.loads(request.content)["windows"]
        posted.append([item["symbol"] for item in batch])
        return httpx.Response(200, json={"protocol": 1, "model": "small", "weights_revision": "fixed",
                                        "predictions": [{"symbol": item["symbol"], "bars": [
                                            {"timestamp": edge, "open": 10, "high": 11, "low": 9, "close": 10}
                                            for edge in item["targets"]]} for item in batch]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(predict)) as client:
        await writer.tick(inputs, markets, client, binance, now)
        await writer.tick(inputs, markets, client, binance, now + timedelta(seconds=3))
    assert posted == [symbols[:10], symbols[10:], ["BTCUSDT"]]
    assert [call.args[2] for call in redis.eval.call_args_list] == list(map(forecast_key, [*symbols, "BTCUSDT"]))
    binance.spot_minute_rows.assert_awaited_once()
    assert len(btc_window(binance_rows(now), now).bars) == 30


@pytest.mark.asyncio
async def test_forecast_read_reuses_stock_entitlement_and_btc_needs_no_stock_lookup(monkeypatch):
    monkeypatch.setattr(market_data, "forecast_url", lambda: "http://mps")
    access = AsyncMock(side_effect=HTTPException(404))
    monkeypatch.setattr(market_data, "_require_intraday_access", access)
    redis = Mock(get=AsyncMock(return_value=None), zrevrangebyscore=AsyncMock(return_value=[]))
    repository = Mock(redis=redis, close=AsyncMock())
    monkeypatch.setattr(market_data.RealtimeStateRepository, "from_url", lambda _: repository)
    request = Mock()
    with pytest.raises(HTTPException) as error:
        await market_data.minute_forecast("AAPL.US", request, Response())
    assert error.value.status_code == 404
    redis.get.assert_not_called()
    assert (await market_data.minute_forecast("BTCUSDT", request, Response())).forecast is None
    redis.get.assert_awaited_once_with(forecast_key("BTCUSDT"))

    access.side_effect = None
    live = ForecastSnapshot(model="small", weights_revision="fixed", symbol="QQQ.US", anchor=0,
                            anchor_close=10, generated_at=60_000, lookback=240,
                            bars=[dict(timestamp=60_000, open=10, high=11, low=9, close=10)])
    replay = live.model_copy(update={"close_replay": True})
    redis.get.reset_mock()
    redis.get.side_effect = [None, replay.model_dump_json()]
    result = await market_data.minute_forecast("QQQ.US", request, Response())
    assert result.forecast == replay and result.comparison is None
    assert [call.args[0] for call in redis.get.call_args_list] == [forecast_key("QQQ.US"), close_replay_key("QQQ.US")]
    redis.get.reset_mock()
    redis.get.side_effect = [live.model_dump_json()]
    assert (await market_data.minute_forecast("QQQ.US", request, Response())).forecast == live
    redis.get.assert_awaited_once_with(forecast_key("QQQ.US"))
