import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest

from finance_analysis.crypto.config import CryptoConfig
from finance_analysis.crypto.service import CryptoService
from finance_analysis.integrations.crypto.binance import BinanceClient, parse_ws
from .helpers import START, candle


@pytest.mark.asyncio
async def test_binance_rest_closed_detection_and_ws_decimals():
    start = int(START.timestamp() * 1000)

    def handle(request):
        if request.url.path.endswith("/time"):
            return httpx.Response(200, json={"serverTime": start + 60000})
        assert request.url.params["symbol"] == "BTCUSDT" and request.url.params["interval"] == "1m"
        return httpx.Response(
            200,
            json=[
                [
                    start + i * 60000,
                    "100",
                    "101",
                    "99",
                    "100.1",
                    "1.123456789012",
                    start + (i + 1) * 60000 - 1,
                    "120",
                    3,
                    "0.1",
                    "12",
                    "0",
                ]
                for i in range(2)
            ],
        )

    client = BinanceClient(
        CryptoConfig(), httpx.AsyncClient(base_url="https://binance.test", transport=httpx.MockTransport(handle))
    )
    rows = await client.klines()
    assert rows[0].closed and not rows[1].closed
    assert rows[0].volume == Decimal("1.123456789012")
    assert rows[0].close_time == START + timedelta(minutes=1)
    frame = dict(
        e="kline",
        s="BTCUSDT",
        E=start + 60000,
        k=dict(
            t=start,
            T=start + 59999,
            s="BTCUSDT",
            i="1m",
            o="100",
            h="101",
            l="99",
            c="100.1",
            v="1.123456789012",
            q="120",
            n=3,
            V="0.1",
            Q="12",
            x=True,
        ),
    )
    assert parse_ws(json.dumps(frame)) == rows[0]
    frame["k"]["i"] = "15m"
    with pytest.raises(ValueError):
        parse_ws(json.dumps(frame))
    await client.close()


@pytest.mark.asyncio
async def test_backfill_paginates_and_retries_from_committed_page(repository):
    end = START + timedelta(minutes=1440)
    calls = []

    class Binance:
        fail = True

        async def server_time(self):
            return end

        async def klines(self, *, start, end, limit, as_of):
            calls.append(start)
            index = int((start - START).total_seconds() // 60)
            if self.fail and index >= 1000:
                self.fail = False
                raise OSError("interrupted")
            return [candle(i) for i in range(index, min(1440, index + limit))]

    service = CryptoService(repository, binance=Binance(), config=CryptoConfig(initial_history_days=1))
    with pytest.raises(OSError):
        await service.backfill()
    assert repository.latest_open_time() == START + timedelta(minutes=999)
    await service.backfill()
    assert calls[2] == START + timedelta(minutes=999)
    assert len(repository.klines(limit=2000, as_of=end)) == 1440
    assert service.live["ready"]
    assert len(repository.signals()) == 1
    await service.backfill()
    assert len(repository.signals()) == 1


@pytest.mark.asyncio
async def test_ingest_does_not_replace_closed_realtime_with_partial_or_replay_snapshot(repository):
    service = CryptoService(repository)
    rows = [candle(i) for i in range(15)]
    await service.ingest(rows)
    await service.ingest([replace(rows[-1], closed=False)])
    assert service.live["latest_candle"]["closed"]
    assert len(service.live["recent_closed"]) == 5
    assert len(repository.signals()) == 1
    snapshot = repository.signals()[0]
    await service.ingest([replace(rows[-1], close=Decimal("100"))])
    assert repository.signals()[0] == snapshot
    assert service.get_strategy_state()["position_state"] == "FLAT"


@pytest.mark.asyncio
async def test_reconciliation_finishes_interrupted_history_before_advancing_to_recent(repository):
    end = START + timedelta(days=1)
    calls = []

    class Binance:
        async def server_time(self):
            return end

        async def klines(self, *, start=None, end=None, limit=5, as_of=None):
            calls.append(start)
            index = 1435 if start is None else int((start - START).total_seconds() // 60)
            return [candle(i) for i in range(index, min(1440, index + limit))]

    repository.upsert_klines([candle(i) for i in range(1000)], end)
    service = CryptoService(repository, binance=Binance())
    await service.reconcile()
    assert calls[0] == START + timedelta(minutes=999)
    assert calls[-1] is None
    assert len(repository.klines(limit=2000, as_of=end)) == 1440
    assert len(repository.signals()) == 1
