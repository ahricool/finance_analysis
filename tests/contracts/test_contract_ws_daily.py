"""Deterministic WS cache and closed daily synchronization contracts."""
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from finance_analysis.contracts import service, daily_sync


DAY = service.DAY
MINUTE = service.MINUTE
NOW = int(datetime(2026, 11, 25, 0, 30, tzinfo=timezone.utc).timestamp() * 1000)
SYMBOL = "BTCUSDT"


def bar(t, price=10):
    return {"timestamp": t, "open": price, "high": price, "low": price,
            "close": price, "volume": 1, "turnover": price}


def event(t, closed=False, price=10, interval="1m", event_time=NOW):
    period = MINUTE if interval == "1m" else DAY
    return {"e": "kline", "s": SYMBOL, "E": event_time, "k": {
        "t": t, "T": t + period - 1, "i": interval, "x": closed,
        "o": str(price), "h": str(price), "l": str(price), "c": str(price), "v": "1", "q": str(price),
    }}


@pytest.mark.asyncio
async def test_ws_quote_and_native_candles_dedup(monkeypatch):
    monkeypatch.setattr(service, "now_ms", lambda: NOW)
    redis = Mock(get=AsyncMock(return_value=None), pipeline=Mock())
    pipe = redis.pipeline.return_value
    pipe.execute = AsyncMock()
    client = Mock(klines=AsyncMock())
    collector = service.ContractCollector(redis, client)
    await collector.load({SYMBOL})
    assert service.stream_url({SYMBOL}).startswith("wss://fstream.binance.com/market/stream?")
    assert "btcusdt@kline_1m" in service.stream_url({SYMBOL})
    collector.accept_event({"e": "markPriceUpdate", "s": SYMBOL, "E": NOW, "r": "0.0001"}, {SYMBOL}, NOW)
    collector.accept_event({"e": "24hrTicker", "s": SYMBOL, "E": NOW, "c": "10", "P": "1.2", "q": "100"},
                           {SYMBOL}, NOW)
    collector.accept_event(event(NOW-MINUTE, closed=True, price=11), {SYMBOL}, NOW)
    collector.accept_event(event(NOW-MINUTE, closed=False, price=9, event_time=NOW+1), {SYMBOL}, NOW)
    collector.accept_event(event(NOW, price=12), {SYMBOL}, NOW)
    collector.accept_event(event(NOW//DAY*DAY, interval="1d"), {SYMBOL}, NOW)
    await collector.flush()
    writes = {call.args[0]: (json.loads(call.args[1]), call.kwargs["ex"]) for call in pipe.set.call_args_list}
    quote, ttl = writes[service.key(SYMBOL, "quote")]
    assert quote["funding_rate"] == 0.0001 and quote["price"] == 10 and ttl == 60
    minutes, ttl = writes[service.key(SYMBOL, "minute")]
    assert minutes[0]["closed"] and minutes[0]["close"] == 11
    assert minutes[1]["close"] == 12 and not minutes[1]["closed"] and ttl == 86400
    assert service.key(SYMBOL, "daily-current") in writes
    client.klines.assert_not_awaited()


@pytest.mark.asyncio
async def test_backfill_does_not_overwrite_websocket_and_repairs_gap(monkeypatch):
    monkeypatch.setattr(service, "now_ms", lambda: NOW)
    redis = Mock(get=AsyncMock(return_value=None))
    collector = service.ContractCollector(redis, Mock())
    await collector.load({SYMBOL})
    started, release = asyncio.Event(), asyncio.Event()

    async def fetch(*_, **__):
        started.set()
        await release.wait()
        return [bar(t) for t in range(service.window_start(NOW), NOW+MINUTE, MINUTE)]

    collector.client.klines = AsyncMock(side_effect=fetch)
    task = asyncio.create_task(collector.repair_minutes(SYMBOL))
    await started.wait()
    collector.accept_event(event(NOW-MINUTE, closed=True, price=20), {SYMBOL}, NOW)
    collector.accept_event(event(NOW, price=21), {SYMBOL}, NOW)
    release.set()
    await task
    assert len(collector.minutes[SYMBOL]) == 1440
    assert collector.minutes[SYMBOL][NOW-MINUTE]["close"] == 20
    assert collector.minutes[SYMBOL][NOW]["close"] == 21
    assert service.complete_minutes(collector.minutes[SYMBOL].values(), NOW)
    del collector.minutes[SYMBOL][NOW-2*MINUTE]
    await collector.repair_minutes(SYMBOL)
    assert service.complete_minutes(collector.minutes[SYMBOL].values(), NOW)
    assert collector.client.klines.await_count == 2


def test_daily_close_and_settle_boundary():
    utc_midnight = NOW//DAY*DAY
    assert daily_sync.target_day(utc_midnight + 29*MINUTE) == utc_midnight-2*DAY
    assert daily_sync.target_day(utc_midnight + 30*MINUTE) == utc_midnight-DAY


@pytest.mark.asyncio
async def test_daily_incremental_complete_or_full_if_internal_gap(monkeypatch):
    target = daily_sync.target_day(NOW)
    listed = target-3*DAY+1000
    actual = {target-3*DAY, target-2*DAY, target-DAY}
    save = Mock()
    monkeypatch.setattr(daily_sync.repository, "daily_timestamps", lambda *_: actual)
    monkeypatch.setattr(daily_sync.repository, "save_daily", save)

    async def fetch(symbol, interval, start, *, limit, end):
        assert end == target+DAY-1 and interval == "1d"
        return [bar(t) for t in range(start, target+DAY, DAY)]

    client = Mock(klines=AsyncMock(side_effect=fetch))
    result = await daily_sync.sync_symbol(client, SYMBOL, listed, target)
    assert result["mode"] == "incremental" and result["bars"] == 1
    save.assert_called_once_with(SYMBOL, [bar(target)])
    actual.add(target)
    result = await daily_sync.sync_symbol(client, SYMBOL, listed, target)
    assert result["mode"] == "up_to_date" and client.klines.await_count == 1
    actual.remove(target-2*DAY)
    result = await daily_sync.sync_symbol(client, SYMBOL, listed, target)
    assert result["mode"] == "full" and result["bars"] == 4
    assert save.call_count == 2


@pytest.mark.asyncio
async def test_daily_partial_response_never_overwrites_history(monkeypatch):
    target = daily_sync.target_day(NOW)
    monkeypatch.setattr(daily_sync.repository, "daily_timestamps", lambda *_: set())
    save = Mock()
    monkeypatch.setattr(daily_sync.repository, "save_daily", save)
    client = Mock(klines=AsyncMock(return_value=[bar(target)]))
    with pytest.raises(daily_sync.DailySyncError):
        await daily_sync.sync_symbol(client, SYMBOL, target-2*DAY, target)
    save.assert_not_called()


@pytest.mark.asyncio
async def test_daily_history_pagination():
    target = daily_sync.target_day(NOW)
    start = target-1824*DAY

    async def fetch(symbol, interval, cursor, *, limit, end):
        return [bar(t) for t in range(cursor, min(target+DAY, cursor+limit*DAY), DAY)]

    client = Mock(klines=AsyncMock(side_effect=fetch))
    rows = await daily_sync.fetch_history(client, SYMBOL, start, target)
    assert len(rows) == 1825 and client.klines.await_count == 2
    assert rows[-1]["timestamp"] == target


@pytest.mark.asyncio
async def test_historical_unconfirmed_minute_is_not_returned_to_strategy(monkeypatch):
    monkeypatch.setattr(service, "now_ms", lambda: NOW)
    rows = [
        {**bar(NOW-2*MINUTE), "closed": True},
        {**bar(NOW-MINUTE), "closed": False},
        {**bar(NOW), "closed": False},
    ]
    redis = Mock(get=AsyncMock(return_value=json.dumps(rows)))
    assert await service.read_json(redis, service.key(SYMBOL, "minute"), []) == [rows[0], rows[2]]


@pytest.mark.asyncio
async def test_disconnect_flushes_received_snapshot_and_subscription_change(monkeypatch):
    monkeypatch.setattr(service, "now_ms", lambda: NOW)
    redis = Mock(get=AsyncMock(return_value=None), pipeline=Mock())
    pipe = redis.pipeline.return_value
    pipe.execute = AsyncMock()
    socket = Mock(recv=AsyncMock(side_effect=[
        json.dumps({"data": event(NOW)}),
        ConnectionError("disconnected"),
    ]))
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def connect(url, **kwargs):
        assert "btcusdt@kline_1m" in url
        yield socket

    collector = service.ContractCollector(redis, Mock(klines=AsyncMock(return_value=[])), connect=connect)
    original = collector.maintain
    async def wait_forever(*_):
        await asyncio.sleep(60)
    monkeypatch.setattr(collector, "maintain", wait_forever)
    with pytest.raises(ConnectionError):
        await collector.run_session({SYMBOL})
    assert any(c.args[0] == service.key(SYMBOL, "minute") for c in pipe.set.call_args_list)
    monkeypatch.setattr(collector, "symbols", AsyncMock(return_value={"ETHUSDT"}))
    with pytest.raises(service.UniverseChanged):
        await original({SYMBOL})


@pytest.mark.asyncio
async def test_initial_backfill_available_even_when_ws_cannot_connect(monkeypatch):
    from contextlib import asynccontextmanager
    monkeypatch.setattr(service, "now_ms", lambda: NOW)
    redis = Mock(get=AsyncMock(return_value=None), pipeline=Mock())
    pipe = redis.pipeline.return_value
    pipe.execute = AsyncMock()
    rows = [bar(t) for t in range(service.window_start(NOW), NOW+MINUTE, MINUTE)]
    client = Mock(klines=AsyncMock(return_value=rows))

    @asynccontextmanager
    async def offline(*_, **__):
        raise ConnectionError("handshake failed")
        yield

    collector = service.ContractCollector(redis, client, connect=offline)
    with pytest.raises(ConnectionError):
        await collector.run_session({SYMBOL})
    assert service.complete_minutes(collector.minutes[SYMBOL].values(), NOW)
    minute_write = next(call for call in pipe.set.call_args_list if call.args[0].endswith(":minute"))
    assert len(json.loads(minute_write.args[1])) == 1440


@pytest.mark.asyncio
async def test_funding_events_do_not_keep_stale_ticker_alive(monkeypatch):
    monkeypatch.setattr(service, "now_ms", lambda: NOW)
    redis = Mock(get=AsyncMock(return_value=None), pipeline=Mock())
    pipe = redis.pipeline.return_value
    pipe.execute = AsyncMock()
    collector = service.ContractCollector(redis, Mock())
    await collector.load({SYMBOL})
    collector.accept_event(
        {"e": "24hrTicker", "s": SYMBOL, "E": NOW, "c": "10", "P": "1.2", "q": "100"}, {SYMBOL}, NOW
    )
    await collector.flush()
    pipe.set.reset_mock()
    pipe.execute.reset_mock()
    later = NOW + 61_000
    monkeypatch.setattr(service, "now_ms", lambda: later)
    collector.accept_event({"e": "markPriceUpdate", "s": SYMBOL, "E": later, "r": "0.0001"}, {SYMBOL}, later)
    await collector.flush()
    assert [call.args[0] for call in pipe.set.call_args_list] == [service.key(SYMBOL, "mark")]
    pipe.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_slow_initial_rest_does_not_delay_live_ws(monkeypatch):
    from contextlib import asynccontextmanager
    monkeypatch.setattr(service, "now_ms", lambda: NOW)
    redis = Mock(get=AsyncMock(return_value=None), pipeline=Mock())
    redis.pipeline.return_value.execute = AsyncMock()
    rest_started = asyncio.Event()
    received = asyncio.Event()

    async def slow_rest(*_, **__):
        rest_started.set()
        await asyncio.Event().wait()

    async def recv():
        await rest_started.wait()
        if not received.is_set():
            received.set()
            return json.dumps({"data": event(NOW, price=15)})
        await asyncio.Event().wait()

    socket = Mock(recv=recv)

    @asynccontextmanager
    async def connect(*_, **__):
        yield socket

    collector = service.ContractCollector(redis, Mock(klines=AsyncMock(side_effect=slow_rest)), connect=connect)
    task = asyncio.create_task(collector.run_session({SYMBOL}))
    try:
        await asyncio.wait_for(received.wait(), timeout=1)
        await asyncio.sleep(0)
        assert collector.minutes[SYMBOL][NOW]["close"] == 15
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_utc_weekend_analysis_spans_midnight_and_excludes_unclosed_minutes():
    from finance_analysis.contracts.analysis import summarize

    midnight = int(datetime(2026, 11, 28, tzinfo=timezone.utc).timestamp() * 1000)
    rows = [{**bar(midnight + i * MINUTE), "closed": i < 2} for i in range(-5, 3)]
    result = summarize(SYMBOL, rows, midnight + 3 * MINUTE)
    assert result["as_of"] == midnight + 2 * MINUTE
    assert result["windows"]["5"]["availableBars"] == 5
    assert result["reference"]
    assert result["trend_1m"]["effective_period"] == 7
    assert result["pattern_1m"]["status"] == "insufficient"


def test_contract_indicators_use_closed_contiguous_weekend_minutes():
    from finance_analysis.contracts.analysis import summarize

    midnight = int(datetime(2026, 11, 28, tzinfo=timezone.utc).timestamp() * 1000)
    prices = [(100, 100.5, 99.5, 100.1 if i % 2 else 99.9) for i in range(15)]
    prices += [(99.8, 100, 98.8, 99.2), (99.3, 100.1, 99.2, 99.8), (99.9, 100.5, 99.8, 100.3)]
    rows = [
        {**bar(midnight + i * MINUTE), "open": o, "high": h, "low": low, "close": c, "closed": True}
        for i, (o, h, low, c) in enumerate(prices)
    ]
    now = midnight + len(rows) * MINUTE
    analysis = summarize(SYMBOL, rows, now)
    assert analysis["trend_1m"]["state"] == "above"
    assert analysis["trend_1m"]["streak"] == 1
    signal = analysis["pattern_1m"]["signal"]
    assert signal["direction"] == "bearish_to_bullish"
    assert signal["stage"] == "confirmed"
    assert signal["trading_date"] == "2026-11-28"
    gap = summarize(SYMBOL, rows[:-3] + rows[-2:], now)
    assert gap["trend_1m"]["effective_period"] == 2
    assert gap["pattern_1m"]["status"] == "insufficient"


def test_rolling_minutes_delta_keeps_unchanged_bars_off_wire():
    from finance_analysis.interfaces.api.v1.schemas.intraday_options_stream import SnapshotStream

    stream = SnapshotStream()
    bars = [bar(i * MINUTE) for i in range(1441)]
    assert stream.encode({"minutes": bars[:-1]})["revision"] == 1
    assert stream.encode({"minutes": bars[1:]})["operations"] == [
        {"op": "remove", "path": ["minutes", 0]},
        {"op": "insert", "path": ["minutes", 1439], "value": bars[-1]},
    ]
    assert stream.encode({"minutes": bars[1:]})["operations"] == []
