import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import httpx
import pytest

from finance_analysis.crypto.config import CryptoConfig
from finance_analysis.crypto.service import CryptoService
from finance_analysis.integrations.crypto.binance import BinanceClient

from .helpers import START, candle


def test_rest_uses_native_intervals_and_excludes_open_candles():
    requests = []

    def handler(request):
        requests.append(request)
        minutes = 15 if request.url.params["interval"] == "15m" else 60
        start = int(START.timestamp() * 1000)
        return httpx.Response(
            200,
            json=[
                [start, "100", "102", "99", "101", "3", start + minutes * 60_000 - 1, "300", 2, "1", "100"],
                [
                    start + minutes * 60_000,
                    "100",
                    "102",
                    "99",
                    "101",
                    "3",
                    start + minutes * 120_000 - 1,
                    "300",
                    2,
                    "1",
                    "100",
                ],
            ],
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://example.test") as http:
            client = BinanceClient(CryptoConfig(), http)
            for interval, minutes in [("15m", 15), ("1h", 60)]:
                end = START + timedelta(minutes=minutes)
                rows = await client.klines(interval=interval, end=end, limit=100)
                assert len(rows) == 1 and rows[0].closed and rows[0].interval == interval
                assert requests[-1].url.params["endTime"] == str(int(end.timestamp() * 1000) - 1)

    asyncio.run(run())


def test_strategy_reads_bounded_closed_windows_and_is_idempotent(repository):
    at = START + timedelta(hours=200, minutes=15)
    client = AsyncMock()
    client.server_time.return_value = at + timedelta(minutes=1)
    quarter = [candle(i) for i in range(701, 801)]
    hourly = [candle(i, interval="1h") for i in range(200)]
    client.klines.side_effect = lambda **kwargs: quarter if kwargs["interval"] == "15m" else hourly
    service = CryptoService(repository, binance=client)
    first = asyncio.run(service.run())
    assert first["strategies"][0]["action"] == "WAIT"
    assert asyncio.run(service.run())["evaluations"] == 0
    assert len(repository.signals("btc_breakout_v1", "BTCUSDT")) == 1
    assert repository.state("btc_breakout_v1", "BTCUSDT").updated_at == at
    client.klines.assert_any_await(interval="15m", end=at, limit=100)
    client.klines.assert_any_await(interval="1h", end=at.replace(minute=0), limit=200)
    client.klines.side_effect = lambda **kwargs: quarter[:-1] if kwargs["interval"] == "15m" else hourly
    client.server_time.return_value = at + timedelta(minutes=16)
    with pytest.raises(ValueError, match="Latest closed"):
        asyncio.run(service.run())
    assert len(repository.signals("btc_breakout_v1", "BTCUSDT")) == 1


def test_schedule_and_route():
    from finance_analysis.tasks.celery.schedule import build_task_routes, require_scheduled_task_definition

    definition = require_scheduled_task_definition("crypto_btc_strategy")
    assert definition.schedules[0].minute == "1,16,31,46"
    assert definition.timezone == "UTC"
    assert build_task_routes()[definition.celery_task_name]["queue"] == "analysis"


def test_catchup_replays_stop_and_exit_in_order_with_only_two_market_requests(repository):
    from decimal import Decimal as D

    from finance_analysis.crypto.models import StrategyState
    from finance_analysis.crypto.strategy import evaluate

    at = START + timedelta(hours=60)
    q = [candle(i, open=D(100), high=D(101), low=D(99), close=D(100)) for i in range(140, 240)]
    h = [candle(i, interval="1h") for i in range(60)]
    state = StrategyState(
        position_pct=D(1),
        average_entry_price=D(100),
        entry_time=START,
        highest_price_since_entry=D(100),
        initial_stop=D(90),
        trailing_stop=D(95),
    )
    repository.evaluate_once("btc_breakout_v1", "BTCUSDT", at, lambda _: evaluate(q, h, at, state))
    q += [
        candle(240, open=D(110), high=D(120), low=D(110), close=D(119)),
        candle(241, open=D(114), high=D(114), low=D(109), close=D(110)),
        candle(242, open=D(115), high=D(116), low=D(114), close=D(115)),
    ]
    # Skipping intermediate bars would hold the old LONG incorrectly.
    assert (
        evaluate(q[-100:], h, at + timedelta(minutes=45), repository.state("btc_breakout_v1", "BTCUSDT"))[1]["action"]
        == "HOLD"
    )
    client = AsyncMock()
    client.server_time.return_value = at + timedelta(minutes=46)
    client.klines.side_effect = lambda **kw: q if kw["interval"] == "15m" else h
    result = asyncio.run(CryptoService(repository, binance=client).run())
    snapshots = list(reversed(repository.signals("btc_breakout_v1", "BTCUSDT", 3)))
    assert [s["evaluated_at"] for s in snapshots] == [at + timedelta(minutes=n) for n in (15, 30, 45)]
    assert [s["action"] for s in snapshots] == ["HOLD", "EXIT", "WAIT"]
    assert snapshots[0]["trailing_stop"] > 95 and repository.state("btc_breakout_v1", "BTCUSDT").position_pct == 0
    assert [(s["position_before"], s["position_after"], s["position_delta"]) for s in snapshots] == [
        (1, 1, 0),
        (1, 0, -1),
        (0, 0, 0),
    ]
    assert result["evaluations"] == 3 and client.klines.await_count == 2


def test_long_downtime_rest_window_pages_without_overlapping_candles():
    requests = []

    def handler(request):
        requests.append(request)
        size = int(request.url.params["limit"])
        end = int(request.url.params["endTime"]) + 1
        return httpx.Response(
            200,
            json=[
                [t, "100", "101", "99", "100", "3", t + 899999, "300", 2, "1", "100"]
                for t in range(end - size * 900000, end, 900000)
            ],
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://example.test") as http:
            result = await BinanceClient(CryptoConfig(), http).klines(
                interval="15m", end=START + timedelta(days=20), limit=1200
            )
            assert len(result) == len({x.open_time for x in result}) == 1200
            assert result[999].close_time == result[1000].open_time

    asyncio.run(run())
    assert [int(r.url.params["limit"]) for r in requests] == [1000, 200]
