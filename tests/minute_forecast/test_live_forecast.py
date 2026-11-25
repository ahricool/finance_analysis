import json
import runpy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import HTTPException, Response

from finance_analysis.integrations.market_data.realtime_state.models import CandleState
from finance_analysis.interfaces.api.v1.endpoints import market_data
from finance_analysis.minute_forecast import publisher
from finance_analysis.minute_forecast.cache import close_replay_key, live_forecast_key, pending_error_key, publish_forecast
from finance_analysis.minute_forecast.evaluation import evaluation_day, read_accuracy, settle_forecasts
from finance_analysis.minute_forecast.models import ForecastAccuracy, ForecastSnapshot, RecentErrors
from finance_analysis.minute_forecast.publisher import ForecastPublisher
from finance_analysis.minute_forecast.windows import millis, stock_close_window, stock_window

MINUTE = timedelta(minutes=1)
NY = ZoneInfo("America/New_York")
SHANGHAI = ZoneInfo("Asia/Shanghai")


def candles(symbol, start, count):
    return [CandleState(symbol, start + i * MINUTE, Decimal(10), Decimal(11), Decimal(9), Decimal(10), 100,
                        Decimal(1000), None, True, start + (i + 1) * MINUTE) for i in range(count)]



def test_stock_forecast_starts_with_fifteen_confirmed_minutes_after_open():
    opened = datetime(2026, 11, 20, 9, 30, tzinfo=NY)
    bars = candles("QQQ.US", opened, 15)
    assert stock_window("QQQ.US", "US", bars, opened + 14 * MINUTE) is None

    first_forecast = opened + 15 * MINUTE
    window = stock_window("QQQ.US", "US", bars, first_forecast)
    assert window is not None
    assert len(window.bars) == 15
    assert window.session_close == millis(opened + 390 * MINUTE)
    assert "session_close" not in window.model_dump()
    assert window.targets == [millis(first_forecast + step * MINUTE) for step in range(60)]

    bars[-1].confirmed = False
    assert stock_window("QQQ.US", "US", bars, first_forecast) is None
    final = opened + 389 * MINUTE
    window = stock_window("QQQ.US", "US", candles("QQQ.US", opened, 389), final)
    assert len(window.bars) == 389 and window.targets == [millis(final)]


def test_candle_window_uses_only_confirmed_observations_and_actual_early_close():
    now = datetime(2026, 11, 27, 12, 58, 7, tzinfo=NY)
    opened = now.replace(hour=9, minute=30, second=0)
    bars = candles("QQQ.US", opened, 209)
    bars[-1].confirmed = False
    value = stock_window("QQQ.US", "US", reversed(bars), now)
    assert value is not None
    assert len(value.bars) == 208 and value.bars[-1].timestamp == millis(now.replace(second=0) - MINUTE)
    assert value.targets == [millis(now.replace(second=0) + i * MINUTE) for i in range(2)]
    bars[1].sampled = True
    assert stock_window("QQQ.US", "US", bars, now) is None
    bars[1].sampled = False
    bars[-2].partial = True
    assert stock_window("QQQ.US", "US", bars, now) is None


def test_cn_forecast_caps_horizon_and_skips_lunch_in_both_directions():
    late = datetime(2026, 11, 20, 11, 28, tzinfo=SHANGHAI)
    morning = candles("600519.SH", late.replace(hour=9, minute=30), 120)
    afternoon = late.replace(hour=13, minute=0)
    pre_lunch = stock_window("600519.SH", "CN", morning, late)
    assert len(pre_lunch.bars) == 118 and len(pre_lunch.targets) == 60
    assert pre_lunch.targets[:3] == [millis(late), millis(late + MINUTE), millis(afternoon)]
    assert stock_window("600519.SH", "CN", morning, late + 2 * MINUTE) is None
    resumed = stock_window("600519.SH", "CN", morning, afternoon)
    assert len(resumed.bars) == 120 and len(resumed.targets) == 60
    assert resumed.bars[-1].timestamp == millis(late + MINUTE)
    window = stock_window("600519.SH", "CN", morning + candles("600519.SH", afternoon, 1), afternoon + MINUTE)
    assert len(window.bars) == 121 and len(window.targets) == 60
    assert window.targets[-1] == millis(afternoon + 60 * MINUTE)


def test_host_accepts_session_windows_and_only_allows_the_exchange_lunch_gap():
    host_request = runpy.run_path(str(Path(__file__).parents[2] / "kronos_worker/server.py"))["Request"]
    afternoon = datetime(2026, 11, 20, 13, tzinfo=SHANGHAI)
    morning = candles("600519.SH", afternoon.replace(hour=9, minute=30), 120)
    for at in (afternoon.replace(hour=11, minute=29), afternoon):
        window = stock_window("600519.SH", "CN", morning, at).model_dump()
        assert len(host_request(protocol=1, windows=[window]).windows[0].targets) == 60
        window["targets"].pop(1)
        with pytest.raises(ValueError, match="targets must follow"):
            host_request(protocol=1, windows=[window])


def test_close_replay_anchors_to_early_close_and_excludes_postmarket_candles():
    close = datetime(2026, 11, 27, 13, 0, tzinfo=NY)
    bars = candles("QQQ.US", close - 32 * MINUTE, 34)
    assert stock_window("QQQ.US", "US", bars, close) is None
    replay = stock_close_window("QQQ.US", "US", bars, close.date())
    assert replay is not None
    assert replay.bars[-1].timestamp == millis(close - MINUTE)
    assert replay.targets == [millis(close + i * MINUTE) for i in range(10)]
    bars[-3].confirmed = False
    assert stock_close_window("QQQ.US", "US", bars, close.date()) is None


@pytest.mark.asyncio
async def test_batches_keep_all_active_stock_symbols(monkeypatch):
    now = datetime(2026, 11, 20, 15, 45, 6, tzinfo=timezone.utc)
    monkeypatch.setattr(publisher, "utc_now", lambda: now)
    redis = Mock(eval=AsyncMock())
    settle = AsyncMock()
    monkeypatch.setattr(publisher, "settle_forecasts", settle)
    writer = ForecastPublisher(redis, "http://mps", "small")
    symbols = [f"STK{i}.US" for i in range(12)]
    inputs = {symbol: candles(symbol, now.replace(second=0) - 75 * MINUTE, 75) for symbol in symbols}
    inputs["REMOVED.US"] = inputs[symbols[0]]
    markets = dict.fromkeys(symbols, "US")
    posted = []

    async def predict(request):
        batch = json.loads(request.content)["windows"]
        posted.append([item["symbol"] for item in batch])
        return httpx.Response(200, json={
            "protocol": 1, "model": "small", "weights_revision": "fixed",
            "predictions": [{"symbol": item["symbol"], "bars": [
                {"timestamp": edge, "open": 10, "high": 11, "low": 9, "close": 10}
                for edge in item["targets"]
            ]} for item in batch],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(predict)) as client:
        await writer.tick(inputs, markets, client, now, set(symbols))
        await writer.tick(inputs, markets, client, now + timedelta(seconds=3), set(symbols))
    assert posted == [symbols[:10], symbols[10:]]
    assert [call.args[2] for call in redis.eval.call_args_list] == list(map(live_forecast_key, symbols))
    settle.assert_awaited_once()
    assert settle.await_args.args[2] == markets


@pytest.mark.asyncio
async def test_next_minute_starts_with_symbols_skipped_when_time_runs_out(monkeypatch):
    opened = datetime(2026, 11, 20, 9, 30, tzinfo=NY)
    minute = opened + 15 * MINUTE
    clock = [minute]
    monkeypatch.setattr(publisher, "utc_now", lambda: clock[0])
    writer = ForecastPublisher(Mock(), "http://mps", "small")
    inputs = {f"STK{i}.US": candles(f"STK{i}.US", opened, 16) for i in range(12)}
    markets = dict.fromkeys(inputs, "US")

    async def finish_at_deadline(_client, batch):
        clock[0] += MINUTE
        return True

    writer.infer = AsyncMock(side_effect=finish_at_deadline)
    await writer.tick(inputs, markets, None, minute, set(inputs))
    assert len(writer.infer.call_args_list) == 1
    await writer.tick(inputs, markets, None, minute + MINUTE, set(inputs))
    assert [window.symbol for window in writer.infer.call_args.args[1]][:2] == list(inputs)[-2:]


@pytest.mark.asyncio
async def test_full_live_path_and_short_accuracy_queue_are_published_together():
    first = millis(datetime(2026, 11, 20, 9, 45, tzinfo=SHANGHAI))
    snapshots = [dict(timestamp=first + 60_000 * i, open=10, high=11, low=9, close=10) for i in range(25)]
    forecast = ForecastSnapshot(symbol="600519.SH", model="small", weights_revision="fixed", anchor=first - 60_000,
                                anchor_close=10, generated_at=first, lookback=15, bars=snapshots,
                                session_close=first + 25 * 60_000)
    redis = Mock(eval=AsyncMock())
    await publish_forecast(redis, forecast)
    args = redis.eval.await_args.args
    assert ForecastSnapshot.model_validate_json(args[6]) == forecast
    assert args[-2] == forecast.session_close
    comparison = ForecastSnapshot.model_validate_json(args[-1])
    assert comparison.bars == forecast.bars[:10] and comparison.session_close is None
    assert args[-4] == comparison.bars[-1].timestamp + 60_000


@pytest.mark.asyncio
async def test_settlement_waits_for_late_bars_and_only_scores_confirmed_observations():
    issued = datetime(2026, 11, 20, 15, 45, tzinfo=NY)
    forecast = ForecastSnapshot(
        symbol="QQQ.US", model="small", weights_revision="fixed", anchor=millis(issued - MINUTE),
        anchor_close=9, generated_at=millis(issued), lookback=240,
        bars=[dict(timestamp=millis(issued + step * MINUTE), open=12, high=13, low=11, close=12)
              for step in range(10)],
    )
    bars = candles("QQQ.US", issued, 10)
    bars[1].partial = True
    bars[3].sampled = True
    bars[5].confirmed = False
    raw = forecast.model_dump_json()
    reads = Mock(execute=AsyncMock(return_value=[[raw]]))
    writes = Mock(execute=AsyncMock(return_value=[]))
    redis = Mock(pipeline=Mock(side_effect=[reads, writes, reads, writes]))
    source = {"QQQ.US": bars}
    markets = {"QQQ.US": "US"}

    await settle_forecasts(redis, source, markets, issued + 10 * MINUTE)
    writes.eval.assert_not_called()
    await settle_forecasts(redis, source, markets, issued + 12 * MINUTE)
    reads.zrangebyscore.assert_called_with(pending_error_key("QQQ.US"), "-inf", millis(issued + 12 * MINUTE))
    _, _, _, date_key, _, original, report, _ = writes.eval.call_args.args
    assert date_key.endswith(":small:2026-11-20") and original == raw
    settled = RecentErrors.model_validate_json(report)
    assert [row.step for row in settled.rows] == [1, 3, 5, 7, 8, 9, 10]
    assert {(row.error, row.baseline_error) for row in settled.rows} == {(2.0, 1.0)}


@pytest.mark.asyncio
async def test_daily_average_divides_errors_by_each_steps_sample_count():
    now = datetime(2026, 11, 21, 0, 5, tzinfo=timezone.utc)
    assert evaluation_day(now, None) == date(2026, 11, 21)
    assert evaluation_day(now, "US") == date(2026, 11, 20)
    totals = {"count:1": "4", "error:1": "6", "baseline:1": "10",
              "count:10": "2", "error:10": "10", "baseline:10": "12"}
    pipe = Mock(execute=AsyncMock(return_value=([None, None], totals)))
    result, previous = await read_accuracy(Mock(pipeline=Mock(return_value=pipe)), "QQQ.US", "small", now.date())
    assert previous is None
    assert [(row.step, row.count, row.mae, row.baseline_mae) for row in result.daily] == [
        (1, 4, 1.5, 2.5), (10, 2, 5.0, 6.0),
    ]
    assert pipe.hgetall.call_args.args[0].endswith(":small:2026-11-21")


@pytest.mark.asyncio
async def test_forecast_read_reuses_stock_entitlement_and_rejects_btc(monkeypatch):
    monkeypatch.setattr(market_data, "forecast_url", lambda: "http://mps")
    accuracy = AsyncMock(side_effect=lambda redis, symbol, model, day: (ForecastAccuracy(trading_date=day), None))
    monkeypatch.setattr(market_data, "read_accuracy", accuracy)
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
    with pytest.raises(HTTPException):
        await market_data.minute_forecast("BTCUSDT", request, Response())
    redis.get.assert_not_called()

    access.side_effect = None
    prefs = Mock()
    prefs.enabled.return_value = False
    monkeypatch.setattr(market_data, "MinuteForecastPreferences", lambda: prefs)
    assert not (await market_data.minute_forecast("QQQ.US", request, Response())).enabled
    redis.get.assert_not_called()
    prefs.enabled.return_value = True
    live = ForecastSnapshot(model="small", weights_revision="fixed", symbol="QQQ.US", anchor=0,
                            anchor_close=10, generated_at=60_000, lookback=240,
                            bars=[dict(timestamp=60_000, open=10, high=11, low=9, close=10)])
    replay = live.model_copy(update={"close_replay": True})
    redis.get.reset_mock()
    redis.get.side_effect = [None, replay.model_dump_json()]
    result = await market_data.minute_forecast("QQQ.US", request, Response())
    assert result.forecast == replay and result.comparison is None
    assert result.accuracy is not None and result.accuracy.daily == []
    assert [call.args[0] for call in redis.get.call_args_list] == [live_forecast_key("QQQ.US"), close_replay_key("QQQ.US")]
    redis.get.reset_mock()
    redis.get.side_effect = [live.model_dump_json()]
    assert (await market_data.minute_forecast("QQQ.US", request, Response())).forecast == live
    redis.get.assert_awaited_once_with(live_forecast_key("QQQ.US"))


@pytest.mark.asyncio
async def test_only_enabled_symbols_with_available_minutes_are_inferred(monkeypatch):
    opened = datetime(2026, 11, 20, 9, 30, tzinfo=NY)
    now = opened + 15 * MINUTE
    monkeypatch.setattr(publisher, "utc_now", lambda: now)
    writer = ForecastPublisher(Mock(), "http://mps", "small")
    writer.infer = AsyncMock(return_value=True)
    inputs = {symbol: candles(symbol, opened, 15) for symbol in ("AAPL.US", "QQQ.US")}
    markets = dict.fromkeys([*inputs, "MISSING.US"], "US")

    await writer.tick(inputs, markets, None, now, set())
    writer.infer.assert_not_awaited()
    await writer.tick(inputs, markets, None, now, {"QQQ.US", "MISSING.US"})
    assert [window.symbol for window in writer.infer.await_args.args[1]] == ["QQQ.US"]
    assert len(writer.infer.await_args.args[1][0].targets) == 60
    writer.infer.reset_mock()
    await writer.tick(inputs, markets, None, now, set())
    writer.infer.assert_not_awaited()


@pytest.mark.asyncio
async def test_shared_preference_endpoint_normalizes_and_persists(monkeypatch):
    prefs = Mock()
    prefs.enabled.return_value = False
    prefs.set_enabled.return_value = True
    monkeypatch.setattr(market_data, "MinuteForecastPreferences", lambda: prefs)
    response = Response()
    assert not (await market_data.get_minute_forecast_preference("00700.HK", response)).enabled
    prefs.enabled.assert_called_once_with("700.HK")
    assert response.headers["Cache-Control"] == "private, no-store"
    from finance_analysis.minute_forecast.models import MinuteForecastPreferencePayload
    assert (await market_data.set_minute_forecast_preference(
        "00700.HK", MinuteForecastPreferencePayload(enabled=True), response,
    )).enabled
    prefs.set_enabled.assert_called_once_with("700.HK", True)
    with pytest.raises(HTTPException):
        await market_data.get_minute_forecast_preference("ABC.SG", response)
