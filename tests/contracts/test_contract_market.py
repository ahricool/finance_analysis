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
from finance_analysis.contracts.underlying import underlying_symbol
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
                    "quoteAsset": "USDT", "marginAsset": "USDT", "underlyingType": "COIN", "baseAsset": "ETH"}
            return httpx.Response(200, json={"symbols": [
                base, {**base, "symbol": "SOXLUSDT", "contractType": "TRADIFI_PERPETUAL", "underlyingType": "EQUITY", "baseAsset": "SOXL"},
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
            {"symbol": "ETHUSDT", "category": "COIN", "base_asset": "ETH"},
            {"symbol": "SOXLUSDT", "category": "EQUITY", "base_asset": "SOXL"},
        ]
        assert (await client.klines("ETHUSDT", "1m", NOW))[0]["close"] == 11
    assert paths == ["/fapi/v1/exchangeInfo", "/fapi/v1/klines"]
    with pytest.raises(ValueError):
        parse_bar([NOW, "10", "8", "9", "11", "2", NOW+59999, "20"])


@pytest.mark.asyncio
async def test_minute_initial_full_warmup_then_no_rest_when_complete(monkeypatch):
    monkeypatch.setattr(service.time, "time", lambda: NOW / 1000)
    redis = Mock(get=AsyncMock(return_value=None), pipeline=Mock())
    redis.pipeline.return_value.execute = AsyncMock()
    rows = [bar(t) for t in range(service.window_start(NOW), NOW + service.MINUTE, service.MINUTE)]
    client = Mock(klines=AsyncMock(return_value=rows))
    collector = service.ContractCollector(redis, client)
    await collector.load({"ETHUSDT"})
    await collector.repair_minutes("ETHUSDT")
    client.klines.assert_awaited_once_with("ETHUSDT", "1m", service.window_start(NOW), limit=1500)
    assert service.complete_minutes(collector.minutes["ETHUSDT"].values(), NOW)
    await collector.repair_minutes("ETHUSDT")
    assert client.klines.await_count == 1
    await collector.flush()
    pipe = redis.pipeline.return_value
    minute_write = next(call for call in pipe.set.call_args_list if call.args[0].endswith(":minute"))
    assert minute_write.kwargs["ex"] == 86400
    assert len(json.loads(minute_write.args[1])) == 1440
    assert not collector.minutes["ETHUSDT"][NOW]["closed"]
    assert collector.minutes["ETHUSDT"][NOW-service.MINUTE]["closed"]


@pytest.mark.asyncio
async def test_snapshot_is_db_scoped_and_missing_quotes_are_null(monkeypatch):
    monkeypatch.setattr(service.repository, "contracts", lambda: [{"symbol": "ETHUSDT", "category": "COIN", "underlying_symbol": "ETH.CRYPTO"}])
    redis = Mock(mget=AsyncMock(return_value=[None]), get=AsyncMock())
    result = await service.live_snapshot(redis, "REMOVEDUSDT")
    assert result["items"] == [{"symbol": "ETHUSDT", "category": "COIN", "underlying_symbol": "ETH.CRYPTO", "quote": None,
                                "analysis": None, "mark": None, "metrics": None, "book": None}]
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
            assert "futures_metric_sample" in inspect(connection).get_table_names()
            symbols = set(connection.execute(text("SELECT symbol FROM futures_contract")).scalars())
            assert len(symbols) == 19 and "BTCUSDT" in symbols and "BTCUSD_PERP" not in symbols
            targets = dict(connection.execute(text("SELECT symbol, underlying_symbol FROM futures_contract")).all())
            assert targets["BTCUSDT"] == "BTC.CRYPTO"
            assert targets["NVDAUSDT"] == "NVDA.US"
            assert targets["SOXLUSDT"] == "SOXL.US"
            assert targets["XAUUSDT"] == "XAU.OTHER"
            assert targets["SKHYUSDT"] == "SKHY.OTHER"
            assert all(targets.values())
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
    monkeypatch.setattr(service.repository, "contracts", lambda: [{"symbol": "ETHUSDT", "category": "COIN", "underlying_symbol": "ETH.CRYPTO"}])
    daily = bar(NOW // service.DAY * service.DAY)
    redis = Mock(mget=AsyncMock(return_value=[None]), get=AsyncMock(return_value=json.dumps(daily)))
    result = await service.live_snapshot(redis, "ETHUSDT", "1d")
    assert result["minutes"] is None and result["daily_current"] == daily
    redis.get.assert_awaited_once_with(service.key("ETHUSDT", "daily-current"))


def test_search_add_duplicate_remove_use_exchange_catalog_and_database(monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from finance_analysis.database.models.contracts import FuturesContract, FuturesDailyBar
    from finance_analysis.interfaces.api.deps import get_db

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    FuturesContract.__table__.create(engine)
    FuturesDailyBar.__table__.create(engine)
    session_factory = sessionmaker(engine)
    api = FastAPI()
    api.include_router(crypto.router, prefix="/api/v1/crypto")

    def session():
        with session_factory() as db:
            yield db

    async def catalog():
        return [{"symbol": "SOXLUSDT", "category": "EQUITY", "underlying_symbol": "SOXL.US"}, {"symbol": "ETHUSDT", "category": "COIN", "underlying_symbol": "ETH.CRYPTO"}]

    monkeypatch.setattr(crypto, "exchange_contracts", catalog)
    api.dependency_overrides[get_db] = session
    api.dependency_overrides[require_admin] = lambda: object()
    with TestClient(api) as client:
        base = "/api/v1/crypto/contracts"
        assert client.get(base + "/search?q=soxl").json() == [{"symbol": "SOXLUSDT", "category": "EQUITY", "underlying_symbol": "SOXL.US"}]
        assert client.post(base, json={"symbol": "BTCUSD_PERP"}).status_code == 422
        payload = {"symbol": "soxlusdt", "category": "ETF", "underlying_symbol": "WRONG.US"}
        created = client.post(base, json=payload)
        assert created.status_code == 201 and created.json() == {"symbol": "SOXLUSDT", "category": "ETF", "underlying_symbol": "SOXL.US"}
        assert client.post(base, json=payload).status_code == 409
        with session_factory() as db:
            assert db.get(FuturesContract, "SOXLUSDT").category == "ETF"
            assert db.get(FuturesContract, "SOXLUSDT").underlying_symbol == "SOXL.US"
        assert client.delete(base + "/SOXLUSDT").status_code == 204
        assert client.delete(base + "/SOXLUSDT").status_code == 404
        with session_factory() as db:
            assert db.get(FuturesContract, "SOXLUSDT") is None
    engine.dispose()


def test_underlying_migration_preserves_custom_universe_and_daily_history():
    engine = create_engine("sqlite://")
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
    config.attributes["connection"] = engine
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE futures_contract (symbol VARCHAR(32) PRIMARY KEY, category TEXT)"))
        connection.execute(text("CREATE TABLE futures_daily_bar (symbol TEXT, timestamp INTEGER, close FLOAT)"))
        connection.execute(text("INSERT INTO futures_contract VALUES ('DOGEUSDT', 'COIN'), ('AAPLUSDT', 'EQUITY'), "
                                "('CUSTOMUSDT', '其他')"))
        connection.execute(text("INSERT INTO futures_daily_bar VALUES ('DOGEUSDT', 1, 0.5)"))
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0100_minute_forecast_optin')"))
    command.upgrade(config, "0101_contract_underlying")
    with engine.connect() as connection:
        assert dict(connection.execute(text("SELECT symbol, underlying_symbol FROM futures_contract")).all()) == {
            "DOGEUSDT": "DOGE.CRYPTO", "AAPLUSDT": "AAPL.US", "CUSTOMUSDT": "CUSTOM.OTHER",
        }
        assert connection.execute(text("SELECT close FROM futures_daily_bar")).scalar() == 0.5
    command.downgrade(config, "0100_minute_forecast_optin")
    assert "underlying_symbol" not in {col["name"] for col in inspect(engine).get_columns("futures_contract")}
    engine.dispose()


@pytest.mark.parametrize("symbol,category,base,expected", [
    ("NVDAUSDT", "EQUITY", "NVDA", "NVDA.US"),
    ("BTCUSDT", "COIN", "BTC", "BTC.CRYPTO"),
    ("ALIASUSDT", "COIN", "ETH", "ETH.CRYPTO"),
    ("SKHYNIXUSDT", "KR_EQUITY", "SKHYNIX", "SKHYNIX.OTHER"),
    ("SPCXUSDT", "EQUITY", "SPCX", "SPCX.OTHER"),
    ("XAUUSDT", "COMMODITY", "XAU", "XAU.OTHER"),
    ("ETHUSDT", "COIN", None, "ETH.CRYPTO"),
    ("USDT", "COIN", None, None),
])
def test_underlying_identity_uses_exchange_base_and_type(symbol, category, base, expected):
    assert underlying_symbol(symbol, category, base) == expected
