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
    assert first["action"] == "WAIT"
    assert asyncio.run(service.run())["action"] == "already_evaluated"
    assert len(repository.signals()) == 1
    assert repository.state().updated_at == at
    client.klines.assert_any_await(interval="15m", end=at, limit=100)
    client.klines.assert_any_await(interval="1h", end=at.replace(minute=0), limit=200)
    client.klines.side_effect = lambda **kwargs: quarter[:-1] if kwargs["interval"] == "15m" else hourly
    with pytest.raises(ValueError, match="Latest closed"):
        asyncio.run(service.run())
    assert len(repository.signals()) == 1


def test_schedule_and_route():
    from finance_analysis.tasks.celery.schedule import build_task_routes, require_scheduled_task_definition

    definition = require_scheduled_task_definition("crypto_btc_strategy")
    assert definition.schedules[0].minute == "1,16,31,46"
    assert definition.timezone == "UTC"
    assert build_task_routes()[definition.celery_task_name]["queue"] == "analysis"
