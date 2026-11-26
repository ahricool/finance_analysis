import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from finance_analysis.contracts import metric_sync as sync, metrics, service
from finance_analysis.database.models.contracts import FuturesMetricSample
from finance_analysis.database.repositories import contracts as repo
from finance_analysis.integrations.crypto.binance import BinanceClient, MarketCooldown
from finance_analysis.interfaces.api.v1.endpoints import crypto

T = 86400000 + 2 * metrics.STEP
S = "BTCUSDT"


def hour():
    start = T - metrics.HOUR
    bars = [{"timestamp": t, "open": 100, "close": 103, "closed": True}
            for t in range(start, T, metrics.MINUTE)]
    prices = metrics.price_buckets(bars, start + metrics.STEP, T, "binance_rest_1m")
    rows = [{"timestamp": start, "oi": {"quantity": 1000}}]
    for i in range(12):
        end = start + (i + 1) * metrics.STEP
        raw = {"timestamp": end - metrics.STEP, "buyVol": 50 if i < 11 else 100,
               "sellVol": 10 if i < 11 else 240, "buySellRatio": 1}
        rows.append({"timestamp": end, "taker": metrics.normalize("taker", [raw], S, end, end)[end],
                     "price": prices[end]})
    rows[-1].update(oi={"quantity": 1080, "usdt": 150000}, accounts={"ratio": 1.5, "long": .6, "short": .4})
    return rows


def test_midnight_exact_window_and_field_local_gaps():
    rows = hour()
    def summary():
        return metrics.summarize_hour(rows, T)
    result = summary()
    assert result["price_change"] == pytest.approx(.03)
    assert result["oi_change"] == pytest.approx(.08)
    assert result["buy_share"] == .65
    assert result["accounts"]["ratio"] == 1.5
    assert result["top_accounts"] is None
    rows[-1]["oi"]["quantity"] = 1000
    assert summary()["oi_change"] == 0
    rows[0]["oi"] = None
    assert summary()["oi_change"] is None
    rows[1]["taker"] = None
    assert summary()["buy_share"] is None and summary()["price_change"] == result["price_change"]
    for row in rows:
        row["taker"] = {"buy": 0, "sell": 0}
    assert summary()["buy_share"] is None
    rows[4].pop("price")
    assert summary()["price_change"] is None
    bars = [{"timestamp": t, "open": 1, "close": 2, "closed": t != T - metrics.MINUTE}
            for t in range(T - metrics.STEP, T, metrics.MINUTE)]
    assert not metrics.price_buckets(bars, T, T, "ws")


@pytest.mark.asyncio
async def test_mark_and_book_ordering_independent_of_ticker(monkeypatch):
    monkeypatch.setattr(service, "now_ms", lambda: T)
    cache = {}
    redis = Mock(get=AsyncMock(side_effect=lambda k: cache.get(k)))
    async def put(k, v, **kwargs):
        cache[k] = v
    redis.set = AsyncMock(side_effect=put)
    collector = service.ContractCollector(redis, Mock())
    await collector.load({S})
    frame = {"s": S, "e": "markPriceUpdate", "p": "101", "i": "100", "r": "0.01", "T": T + metrics.HOUR, "E": T}
    collector.accept_event(frame, {S}, T)
    collector.accept_event({**frame, "E": T - 1, "p": 98}, {S}, T)
    assert collector.funding[S]["basis"] == pytest.approx(.01)
    monkeypatch.setattr(sync, "now_ms", lambda: T)
    book = sync.book_snapshot({"bidPrice": "99.99", "askPrice": "100.01", "time": T})
    assert book["spread_bps"] == pytest.approx(2)
    await sync.cache_fresh(redis, S, "book", book, 60)
    await sync.cache_fresh(redis, S, "book", {**book, "timestamp": T - 1}, 60)
    assert json.loads(cache[service.key(S, "book")]) == book
    assert sync.depth_snapshot({"T": T, "bids": [["10", "2"]], "asks": [["11", "3"]]}) == {
        "timestamp": T, "bids": 20, "bids_levels": 1, "asks": 33, "asks_levels": 1}


@pytest.mark.asyncio
async def test_dedicated_header_origin_and_cooldown(monkeypatch):
    monkeypatch.setenv("BINANCE_FUTURES_MARKET_DATA_KEY", "test-only-key")
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[]) if len(calls) == 1 else httpx.Response(429, headers={"Retry-After": "60"})
    for base in ("https://mirror.invalid", "https://fapi.binance.com"):
        async with httpx.AsyncClient(base_url=base, transport=httpx.MockTransport(handler)) as http:
            client = BinanceClient(http)
            if "mirror" in base:
                with pytest.raises(PermissionError):
                    await client.market_get("/futures/data/topLongShortAccountRatio", private_stats=True)
                assert not calls
            else:
                await client.market_get("/futures/data/topLongShortAccountRatio", private_stats=True)
                assert calls[-1].headers["X-MBX-APIKEY"] == "test-only-key"
                with pytest.raises(httpx.HTTPStatusError):
                    await client.market_get("/fapi/v1/depth")
                assert "X-MBX-APIKEY" not in calls[-1].headers
                with pytest.raises(MarketCooldown):
                    await client.market_get("/fapi/v1/depth")
                assert len(calls) == 2


def test_history_upsert_partial_pagination_and_bounds(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    FuturesMetricSample.__table__.create(engine)
    @contextmanager
    def session():
        with Session(engine) as db, db.begin():
            yield db
    monkeypatch.setattr(repo.DatabaseManager, "get_instance", lambda: Mock(session_scope=session))
    prices = {t: {"open": 10, "close": 11, "source": "binance_rest_1m", "source_time": t - metrics.STEP}
              for t in (T, T + metrics.STEP)}
    repo.save_samples(S, "price", prices)
    repo.save_samples(S, "price", prices)
    repo.save_samples(S, "oi", {T: {"quantity": 1000, "usdt": 10000, "source_time": T}})
    app = FastAPI()
    app.include_router(crypto.router)
    url = f"/contracts/{S}/metrics"
    with TestClient(app) as client:
        page = client.get(url, params={"start": T, "end": T + metrics.STEP, "limit": 1}).json()
        first, = page["items"]
        assert first["oi"]["quantity"] == 1000 and first["price"] == prices[T] and first["top_accounts"] is None
        next_page = client.get(url, params={"start": page["next_start"], "end": T + metrics.STEP}).json()
        assert next_page["next_start"] is None and len(next_page["items"]) == 1
        assert client.get(url, params={"start": T, "end": T, "limit": 501}).status_code == 422
        assert client.get(url, params={"start": 0, "end": 32 * metrics.DAY}).status_code == 422
    engine.dispose()


@pytest.mark.asyncio
async def test_backfill_resumes_page_and_skips_stored_boundaries(monkeypatch):
    end = 100 * metrics.DAY
    cursor = end - metrics.HOUR
    start = cursor - (sync.PAGE - 1) * metrics.STEP
    redis = Mock(get=AsyncMock(return_value=str(cursor)), set=AsyncMock())
    monkeypatch.setattr(repo, "sample_times", lambda *_: {start, cursor})
    fetch = AsyncMock(side_effect=ConnectionError)
    monkeypatch.setattr(sync, "collect", fetch)
    with pytest.raises(ConnectionError):
        await sync.backfill_page(redis, Mock(), S, "oi", end)
    redis.set.assert_not_awaited()
    fetch.side_effect = None
    await sync.backfill_page(redis, Mock(), S, "oi", end)
    assert fetch.await_args.args[4:] == (start + metrics.STEP, cursor - metrics.STEP, False)
    assert redis.set.await_args.args[1] == start - metrics.STEP


@pytest.mark.asyncio
async def test_latest_partial_tradfi_preserves_successes_and_retries(monkeypatch):
    rows = hour()
    monkeypatch.setattr(repo, "metric_history", lambda *_: rows)
    requests = []
    async def collect(redis, client, symbol, source, start, end, recent):
        requests.append(source)
        if source.startswith("top_"):
            raise PermissionError
        if source == "oi":
            raise MarketCooldown
        return set()
    monkeypatch.setattr(sync, "collect", collect)
    redis = Mock(set=AsyncMock())
    assert await sync.latest(redis, Mock(), [S], T) == {S}
    published = json.loads(redis.set.await_args.args[1])
    assert published["oi_change"] == pytest.approx(.08) and published["buy_share"] == .65
    assert published["top_positions"] is None and published["status"]["top_accounts"] == "unauthorized"
    assert published["status"]["oi"] == "rate_limited"


@pytest.mark.asyncio
async def test_old_quote_and_new_snapshots_have_identical_wire_fields_and_expire(monkeypatch):
    from finance_analysis.interfaces.api.v1.schemas.contracts import MarketSnapshot
    from finance_analysis.interfaces.api.v1.schemas.intraday_options_stream import SnapshotStream

    monkeypatch.setattr(service, "now_ms", lambda: T)
    monkeypatch.setattr(repo, "contracts", lambda: [{"symbol": S, "category": "COIN", "underlying_symbol": None}])
    cache = {service.key(S, "quote"): {"timestamp": T, "price": 100, "turnover": 10, "change_pct": 1,
                                       "funding_rate": .001}}
    async def mget(keys):
        return [json.dumps(cache[k]) if k in cache else None for k in keys]
    redis = Mock(mget=mget)
    stream = SnapshotStream()
    old = await service.live_snapshot(redis)
    assert old["items"][0]["metrics"] is None and old["items"][0]["quote"]["price"] == 100
    assert stream.encode(old) == {**MarketSnapshot.model_validate(old).model_dump(exclude_unset=True), "revision": 1}
    summary = metrics.summarize_hour([], T)
    summary["status"] = {"oi": "missing"}
    cache[service.key(S, "metrics")] = summary
    current = await service.live_snapshot(redis)
    assert current == MarketSnapshot.model_validate(current).model_dump(exclude_unset=True)
    assert stream.encode(current)["operations"] == [{"op": "set", "path": ["items", 0, "metrics"], "value": summary}]
    monkeypatch.setattr(service, "now_ms", lambda: T + metrics.STEP)
    expired = stream.encode(await service.live_snapshot(redis))
    assert {"op": "set", "path": ["items", 0, "metrics"], "value": None} in expired["operations"]


@pytest.mark.asyncio
async def test_price_repair_failure_preserves_complete_cache_buckets(monkeypatch):
    saved = Mock()
    monkeypatch.setattr(repo, "save_samples", saved)
    bars = [{"timestamp": t, "open": 100, "close": 103, "closed": True}
            for t in range(T - metrics.STEP, T, metrics.MINUTE)]
    monkeypatch.setattr(sync, "read_json", AsyncMock(return_value=bars))
    with pytest.raises(ConnectionError):
        await sync.collect(None, Mock(klines=AsyncMock(side_effect=ConnectionError)),
                           S, "price", T - metrics.STEP, T, True)
    assert list(saved.call_args.args[-1]) == [T]


@pytest.mark.asyncio
async def test_taker_range_parameters_and_source_timestamp(monkeypatch):
    saved = Mock()
    monkeypatch.setattr(repo, "save_samples", saved)
    monkeypatch.setattr(sync, "now_ms", lambda: T + 1000)
    client = Mock(market_get=AsyncMock(return_value=[
        {"timestamp": T - metrics.STEP, "buyVol": 5, "sellVol": 2, "buySellRatio": 2.5},
        {"timestamp": T, "buyVol": 100, "sellVol": 1, "buySellRatio": 100},
    ]))
    await sync.collect(None, client, S, "taker", T, T, True)
    params = client.market_get.await_args.args[1]
    assert params["startTime"] == T and params["endTime"] == T + 1000
    assert saved.call_args.args[-1] == {T: {"source_time": T - metrics.STEP, "buy": 5, "sell": 2, "ratio": 2.5}}
