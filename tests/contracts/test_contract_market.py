import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from finance_analysis.contracts import service
from finance_analysis.integrations.crypto.binance import BinanceClient, parse_bar
from finance_analysis.interfaces.api.v1.endpoints import crypto
from finance_analysis.interfaces.api.middlewares.auth import add_auth_middleware
from finance_analysis.interfaces.api.deps import require_admin

NOW = int(datetime(2026, 11, 25, 4, 5, tzinfo=timezone.utc).timestamp() * 1000)


def bar(timestamp, price=10):
    return {"timestamp": timestamp, "open": price, "high": price, "low": price,
            "close": price, "volume": 1, "turnover": price}


def test_window_is_exactly_1440_minutes_merges_corrected_bar_and_excludes_future():
    minute = service.minute_start(NOW)
    old = [bar(minute - i * service.MINUTE) for i in reversed(range(1442))]
    fresh = [bar(minute, 12), bar(minute + service.MINUTE)]
    actual = service.merge_minutes(old, fresh, NOW)
    assert len(actual) == 1440
    assert actual[0]["timestamp"] == minute - 1439 * service.MINUTE
    assert actual[-1] == bar(minute, 12)


@pytest.mark.asyncio
async def test_binance_usdm_only_and_native_kline():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("exchangeInfo"):
            base = {"symbol": "ETHUSDT", "contractType": "PERPETUAL", "status": "TRADING",
                    "quoteAsset": "USDT", "marginAsset": "USDT", "underlyingType": "COIN"}
            return httpx.Response(200, json={"symbols": [
                base, {**base, "symbol": "SOXLUSDT", "contractType": "TRADIFI_PERPETUAL", "underlyingType": "EQUITY"},
                {**base, "symbol": "BTCUSD_PERP", "marginAsset": "BTC"},
                {**base, "symbol": "ETHUSDC", "quoteAsset": "USDC"},
                {**base, "symbol": "ETHUSDT_261231", "contractType": "CURRENT_QUARTER"},
                {**base, "symbol": "STALEUSDT", "status": "SETTLING"},
            ]})
        assert request.url.params["interval"] == "1m"
        assert int(request.url.params["startTime"]) == NOW
        return httpx.Response(200, json=[[NOW, "10", "12", "9", "11", "2", NOW+59999, "20"]])
    async with httpx.AsyncClient(base_url="https://test.invalid", transport=httpx.MockTransport(handler)) as http:
        client = BinanceClient(http)
        assert await client.contracts() == [
            {"symbol": "ETHUSDT", "category": "COIN"}, {"symbol": "SOXLUSDT", "category": "EQUITY"},
        ]
        assert (await client.klines("ETHUSDT", "1m", NOW))[0]["close"] == 11
    assert paths == ["/fapi/v1/exchangeInfo", "/fapi/v1/klines"]
    with pytest.raises(ValueError):
        parse_bar([NOW, "10", "8", "9", "11", "2", NOW+59999, "20"])


@pytest.mark.asyncio
async def test_minute_refresh_full_then_incremental_and_closed_daily_only(monkeypatch):
    monkeypatch.setattr(service.time, "time", lambda: NOW / 1000)
    redis = Mock(get=AsyncMock(return_value=None), set=AsyncMock())
    client = Mock(klines=AsyncMock(return_value=[bar(NOW)]))
    collector = service.ContractCollector(redis, client)
    await collector.minute_tick("ETHUSDT")
    client.klines.assert_awaited_once_with("ETHUSDT", "1m", service.window_start(NOW), limit=1500)
    assert redis.set.await_args.kwargs["ex"] == 86400
    redis.get.return_value = json.dumps([bar(NOW-service.MINUTE)])
    await collector.minute_tick("ETHUSDT")
    client.klines.assert_awaited_with("ETHUSDT", "1m", NOW-3*service.MINUTE, limit=99)
    assert len(json.loads(redis.set.await_args.args[1])) == 2

    today = NOW // service.DAY * service.DAY
    monkeypatch.setattr(service.repository, "latest_daily", lambda _: today-service.DAY)
    save = Mock()
    monkeypatch.setattr(service.repository, "save_daily", save)
    client.klines.return_value = [bar(today-service.DAY), bar(today)]
    await collector.daily_tick("ETHUSDT")
    save.assert_called_once_with("ETHUSDT", [bar(today-service.DAY)])
    assert json.loads(redis.set.await_args.args[1]) == bar(today)


@pytest.mark.asyncio
async def test_snapshot_is_db_scoped_and_missing_quotes_are_null(monkeypatch):
    monkeypatch.setattr(service.repository, "contracts", lambda: [{"symbol": "ETHUSDT", "category": "COIN"}])
    redis = Mock(mget=AsyncMock(return_value=[None]), get=AsyncMock())
    result = await service.live_snapshot(redis, "REMOVEDUSDT")
    assert result["items"] == [{"symbol": "ETHUSDT", "category": "COIN", "quote": None}]
    assert result["minutes"] is None
    redis.get.assert_not_called()


def test_old_tables_removed_and_default_seed_runs_once_on_fresh_and_existing_db():
    for existing in (True, False):
        engine = create_engine("sqlite://")
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
        with engine.begin() as connection:
            if existing:
                connection.execute(text("CREATE TABLE crypto_strategy_state (symbol TEXT)"))
                connection.execute(text("CREATE TABLE crypto_strategy_snapshot (symbol TEXT)"))
                connection.execute(text("CREATE TABLE task (task_type TEXT, scheduler_job_id TEXT)"))
                connection.execute(text("INSERT INTO task VALUES ('scheduled_crypto_btc_strategy', NULL), ('other', NULL)"))
                connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
                connection.execute(text("INSERT INTO alembic_version VALUES ('0095_daily_forecast_accuracy')"))
        config.attributes["connection"] = engine
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert not {"crypto_strategy_state", "crypto_strategy_snapshot"}.intersection(
                inspect(connection).get_table_names()
            )
            symbols = set(connection.execute(text("SELECT symbol FROM futures_contract")).scalars())
            assert len(symbols) == 19 and "BTCUSDT" in symbols and "BTCUSD_PERP" not in symbols
            if existing:
                assert connection.execute(text("SELECT task_type FROM task")).scalars().all() == ["other"]
            connection.execute(text("DELETE FROM futures_contract WHERE symbol = 'BTCUSDT'"))
            connection.commit()
            command.upgrade(config, "head")
            assert connection.execute(text("SELECT COUNT(*) FROM futures_contract")).scalar() == 18
        engine.dispose()


def test_session_auth_and_admin_mutation_boundary():
    api = FastAPI()
    api.include_router(crypto.router, prefix="/api/v1/crypto")
    add_auth_middleware(api)
    with TestClient(api) as client:
        assert client.get("/api/v1/crypto/contracts").status_code == 401
        assert client.post("/api/v1/crypto/contracts", json={"symbol": "ETHUSDT"}).status_code == 401
        with client.websocket_connect("/api/v1/crypto/contracts/ws") as ws:
            from starlette.websockets import WebSocketDisconnect
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 4401
    assert any(dep.call is require_admin for route in api.routes for dep in getattr(
        getattr(route, "dependant", None), "dependencies", []
    ))


@pytest.mark.asyncio
async def test_redis_outage_does_not_hide_database_universe(monkeypatch):
    monkeypatch.setattr(service.repository, "contracts", lambda: [{"symbol": "SOXLUSDT", "category": "ETF"}])
    redis = Mock(mget=AsyncMock(side_effect=RedisConnectionError), get=AsyncMock(side_effect=RedisConnectionError))
    result = await service.live_snapshot(redis, "SOXLUSDT", "1m")
    assert result["items"][0]["quote"] is None
    assert result["minutes"] == []
    assert result["daily_current"] is None


@pytest.mark.asyncio
async def test_stream_requested_period_isolated(monkeypatch):
    monkeypatch.setattr(service.time, "time", lambda: NOW / 1000)
    monkeypatch.setattr(service.repository, "contracts", lambda: [{"symbol": "ETHUSDT", "category": "COIN"}])
    daily = bar(NOW // service.DAY * service.DAY)
    redis = Mock(mget=AsyncMock(return_value=[None]), get=AsyncMock(return_value=json.dumps(daily)))
    result = await service.live_snapshot(redis, "ETHUSDT", "1d")
    assert result["minutes"] is None and result["daily_current"] == daily
    redis.get.assert_awaited_once_with(service.key("ETHUSDT", "daily-current"))
