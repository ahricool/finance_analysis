from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from finance_analysis.database.models.live_trade import (
    LiveTradeControl,
    LiveTradeControlEvent,
    LiveExchangeRecord,
    LiveAccountSnapshot,
)
from finance_analysis.database.models.paper_trade import PaperIntent, PaperTradeControl, PaperStrategy
from finance_analysis.database.repositories import live_trade as repo, contracts
from finance_analysis.integrations.crypto.binance_live import LiveReader, LiveReadError
from finance_analysis.interfaces.api.deps import require_admin
from finance_analysis.interfaces.api.middlewares.auth import add_auth_middleware
from finance_analysis.interfaces.api.v1.endpoints import live_trade
from finance_analysis.live_trade.config import LiveConfig
from finance_analysis.live_trade.gateway import Action, LiveIntent, LiveGateway, ExecutionDenied, STRATEGIES
from finance_analysis.live_trade.runtime import LiveMonitor, now_ms

MODELS = (LiveTradeControl, LiveTradeControlEvent, LiveExchangeRecord, LiveAccountSnapshot)


@pytest.fixture
def live_db(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    for model in (*MODELS, PaperIntent, PaperTradeControl, PaperStrategy):
        model.__table__.create(engine)
    factory = sessionmaker(engine)

    @contextmanager
    def session():
        with factory.begin() as db:
            yield db

    monkeypatch.setattr(repo, "session_scope", session)
    from finance_analysis.database.repositories import paper_trade

    monkeypatch.setattr(paper_trade, "session_scope", session)
    yield engine
    engine.dispose()


@pytest.mark.parametrize("enabled", [False, True])
def test_gateway_all_actions_denied_with_empty_registry(enabled):
    assert not STRATEGIES
    gateway = LiveGateway(state_reader=lambda: {"enabled": enabled})
    for action in Action:
        intent = LiveIntent("unregistered", "BTCUSDT", action, "mock-request")
        with pytest.raises(
            ExecutionDenied, match="LIVE_STRATEGY_NOT_REGISTERED" if enabled else "LIVE_TRADING_DISABLED"
        ):
            gateway.submit(intent)
    assert not hasattr(gateway, "client")
    with pytest.raises(ExecutionDenied, match="LIVE_EXECUTION_NOT_IMPLEMENTED"):
        LiveGateway(state_reader=lambda: {"enabled": True}, registry={"mock": object()}).submit(
            LiveIntent("mock", "BTCUSDT", Action.CLOSE, "mock-request")
        )

    def broken():
        raise IOError("database unavailable")

    with pytest.raises(ExecutionDenied, match="LIVE_CONTROL_UNAVAILABLE"):
        LiveGateway(state_reader=broken).submit(LiveIntent("mock", "BTCUSDT", Action.OPEN, "id"))


def test_control_default_persistence_audit_account_isolation(live_db):
    assert repo.control() == {"enabled": False, "updated_at": None}
    assert repo.set_control(True, 7)["enabled"] is True
    assert repo.control()["enabled"] is True
    from finance_analysis.database.repositories import paper_trade

    assert paper_trade.trade_control()["enabled"] is False
    paper_trade.set_trade_control(True)
    repo.set_control(True, 7)
    repo.bind("live-account")
    assert repo.control()["enabled"] is True
    repo.set_control(False, 42)
    assert repo.control()["enabled"] is False
    assert paper_trade.trade_control()["enabled"] is True
    assert [(e["actor_id"], e["previous"], e["enabled"]) for e in repo.events()] == [
        (42, True, False),
        (7, False, True),
    ]
    with pytest.raises(ValueError, match="LIVE_ACCOUNT_CHANGED"):
        repo.bind("other-account")
    assert not repo.records("order")
    with live_db.connect() as conn:
        assert conn.execute(PaperIntent.__table__.select()).all() == []


@pytest.mark.asyncio
async def test_production_transport_read_allowlist_no_trade_writes(caplog):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "fapi.binance.com"
        assert "mock-secret" not in str(request.url)
        if request.url.path == "/fapi/v1/listenKey":
            assert request.method in {"POST", "PUT"}
            return httpx.Response(200, json={"listenKey": "mock-listen"})
        assert request.method == "GET"
        assert request.headers["X-MBX-APIKEY"] == "mock-key"
        assert "signature" in request.url.params
        return httpx.Response(200, json={"totalWalletBalance": "123"})

    client = LiveReader(LiveConfig("mock-key", "mock-secret"), httpx.MockTransport(handler))
    try:
        await client.account()
        await client.listen()
        await client.listen("PUT")
        for method in ("POST", "PUT", "DELETE"):
            for path in (
                "/fapi/v1/order",
                "/fapi/v1/algoOrder",
                "/fapi/v1/batchOrders",
                "/fapi/v1/leverage",
                "/fapi/v1/marginType",
                "/fapi/v1/positionSide/dual",
                "/sapi/v1/asset/transfer",
            ):
                with pytest.raises(LiveReadError, match="READ_ONLY_TRANSPORT"):
                    await client._request(method, path)
        assert len(calls) == 3
    finally:
        await client.close()
    assert "mock-key" not in caplog.text and "mock-secret" not in caplog.text and "signature=" not in caplog.text


@pytest.mark.asyncio
async def test_monitor_sync_with_switch_off_on_restart_and_existing_positions(live_db, monkeypatch):
    monkeypatch.setattr(contracts, "contracts", lambda: [{"symbol": "BTCUSDT"}])
    stamp = now_ms() - 100
    account = {"totalWalletBalance": "1000.12", "totalMarginBalance": "1005.12", "availableBalance": "900"}
    position = {
        "symbol": "BTCUSDT",
        "positionSide": "BOTH",
        "positionAmt": "0.001",
        "entryPrice": "100000",
        "markPrice": "105000",
        "unRealizedProfit": "5",
    }
    order = {
        "symbol": "BTCUSDT",
        "orderId": 12345678901234567,
        "clientOrderId": "app-order",
        "status": "NEW",
        "side": "BUY",
        "origQty": "0.002",
        "updateTime": stamp,
    }
    algo = {
        "symbol": "BTCUSDT",
        "algoId": 555,
        "clientAlgoId": "app-algo",
        "algoStatus": "NEW",
        "quantity": "0.001",
        "updateTime": stamp,
    }
    fills = [
        {
            "symbol": "BTCUSDT",
            "orderId": order["orderId"],
            "id": 777,
            "side": "BUY",
            "qty": "0.001",
            "price": "100000",
            "commission": "0.01",
            "commissionAsset": "USDT",
            "realizedPnl": "0",
            "time": stamp,
        }
    ]
    income = [
        {
            "symbol": "BTCUSDT",
            "tranId": 111,
            "incomeType": "COMMISSION",
            "asset": "USDT",
            "income": "-0.01",
            "time": stamp,
        },
        {"symbol": "", "tranId": 222, "incomeType": "TRANSFER", "asset": "USDT", "income": "1000", "time": stamp},
    ]
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "fapi.binance.com"
        values = {
            "/fapi/v1/time": {"serverTime": now_ms()},
            "/fapi/v3/account": account,
            "/fapi/v3/balance": [{"accountAlias": "live-only", "asset": "USDT", "balance": "1000.12"}],
            "/fapi/v3/positionRisk": [position, {**position, "symbol": "ETHUSDC"}],
            "/fapi/v1/accountConfig": {"dualSidePosition": False},
            "/fapi/v1/symbolConfig": [{"symbol": "BTCUSDT", "leverage": 2, "marginType": "ISOLATED"}],
            "/fapi/v1/exchangeInfo": {
                "symbols": [
                    {"symbol": "BTCUSDT", "contractType": "PERPETUAL", "marginAsset": "USDT", "quoteAsset": "USDT"},
                    {"symbol": "ETHUSDC", "contractType": "PERPETUAL", "marginAsset": "USDC", "quoteAsset": "USDC"},
                ]
            },
            "/fapi/v1/premiumIndex": {"lastFundingRate": "0.0001"},
            "/fapi/v1/openOrders": [order] if order["status"] == "NEW" else [],
            "/fapi/v1/openAlgoOrders": [algo] if algo["algoStatus"] == "NEW" else [],
            "/fapi/v1/allOrders": [order],
            "/fapi/v1/allAlgoOrders": [algo],
            "/fapi/v1/order": order,
            "/fapi/v1/algoOrder": algo,
            "/fapi/v1/income": income,
            "/fapi/v1/userTrades": fills,
        }
        assert request.url.path in values
        return httpx.Response(200, json=values[request.url.path])

    reader = LiveReader(LiveConfig("test-key", "test-secret"), httpx.MockTransport(handler))
    try:
        monitor = LiveMonitor(Mock(), reader)
        first = await monitor.sync()
        assert first["complete"] and len(first["positions"]) == 1
        assert first["positions"][0]["source"] == "EXTERNAL"
        assert first["positions"][0]["fundingRate"] == "0.0001"
        assert first["open_orders"][0]["orderId"] == str(order["orderId"])
        assert not repo.control()["enabled"]
        repo.set_control(True, 1)
        monitor = LiveMonitor(Mock(), reader)
        order.update(status="FILLED", updateTime=stamp + 1)
        algo.update(algoStatus="CANCELED", updateTime=stamp + 1)
        await monitor.sync()
        assert repo.control()["enabled"] is True
        assert repo.records("order")[0]["status"] == "FILLED"
        assert repo.records("algo")[0]["algoStatus"] == "CANCELED"
        assert len(repo.records("trade")) == 1
        event = {
            "e": "ORDER_TRADE_UPDATE",
            "T": stamp + 2,
            "o": {
                "s": "BTCUSDT",
                "i": order["orderId"],
                "c": "app-order",
                "S": "BUY",
                "o": "LIMIT",
                "X": "FILLED",
                "x": "TRADE",
                "q": "0.001",
                "z": "0.001",
                "t": 777,
                "l": "0.001",
                "L": "100000",
                "rp": "0",
                "n": "0.01",
                "N": "USDT",
                "ps": "BOTH",
                "T": stamp,
            },
        }
        await monitor.event(event)
        await monitor.event(event)
        assert len(repo.records("trade")) == 1
        result = live_trade.data()
        assert result["environment"] == "LIVE" and result["strategy_count"] == 0
        assert result["realized_net"] == "-0.01"
        assert all(t["source"] == "EXTERNAL" for t in result["trades"])
        assert all(r.method == "GET" for r in calls)
    finally:
        await reader.close()


def test_live_admin_api_only_local_state_no_order_routes(live_db, monkeypatch):
    monkeypatch.setenv("BINANCE_LIVE_API_KEY", "")
    monkeypatch.setenv("BINANCE_LIVE_API_SECRET", "")
    app = FastAPI()
    app.include_router(live_trade.router, prefix="/api/v1/crypto/live-trade")
    add_auth_middleware(app)
    with TestClient(app) as client:
        assert client.get("/api/v1/crypto/live-trade").status_code == 401
        assert client.put("/api/v1/crypto/live-trade/control", json={"enabled": True}).status_code == 401
    app = FastAPI()
    app.include_router(live_trade.router, prefix="/api/v1/crypto/live-trade")

    def deny():
        raise HTTPException(403, "Admin required")

    app.dependency_overrides[require_admin] = deny
    with TestClient(app) as client:
        assert client.put("/api/v1/crypto/live-trade/control", json={"enabled": True}).status_code == 403
    app.dependency_overrides[require_admin] = lambda: Mock(id=5)
    with TestClient(app) as client:
        path = "/api/v1/crypto/live-trade"
        response = client.get(path)
        assert response.headers["Cache-Control"] == "private, no-store"
        initial = response.json()
        assert initial["connection"]["status"] == "NOT_CONFIGURED"
        assert initial["control"]["enabled"] is False and initial["view"] is None
        assert client.put(path + "/control", json={"enabled": "true"}).status_code == 422
        assert client.put(path + "/control", json={"enabled": True}).json()["enabled"] is True
        assert client.get(path + "/control").json()["enabled"] is True
        assert client.get(path).json()["strategy_count"] == 0
        for endpoint in ("orders", "cancel", "close", "leverage", "conditional"):
            assert client.post(path + "/" + endpoint, json={}).status_code == 404
        assert client.put(path + "/control", json={"enabled": False}).json()["enabled"] is False
        assert len(repo.events()) == 2


@pytest.mark.asyncio
async def test_missing_credentials_does_not_construct_reader(monkeypatch):
    from finance_analysis.live_trade import runtime

    monkeypatch.setenv("BINANCE_LIVE_API_KEY", "")
    monkeypatch.setenv("BINANCE_LIVE_API_SECRET", "")
    constructor = Mock(side_effect=AssertionError("must not construct reader"))
    monkeypatch.setattr(runtime, "LiveReader", constructor)
    await runtime.run_live_monitor(Mock())
    constructor.assert_not_called()


def test_live_migration_preserves_demo_tables():
    import importlib.util
    from pathlib import Path
    from alembic.operations import Operations
    from alembic.migration import MigrationContext
    from sqlalchemy import text

    path = Path(__file__).parents[2] / "alembic" / "versions" / "0098_live_trade.py"
    spec = importlib.util.spec_from_file_location("live_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE paper_strategy (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO paper_strategy VALUES (1)"))
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        for model in MODELS:
            assert {c["name"] for c in inspect(conn).get_columns(model.__tablename__)} == set(
                model.__table__.columns.keys()
            )
        migration.downgrade()
        assert conn.execute(text("SELECT id FROM paper_strategy")).scalar() == 1
    engine.dispose()


@pytest.mark.asyncio
async def test_auth_failure_state_does_not_create_stream_or_write():
    import asyncio
    from unittest.mock import AsyncMock

    reader = Mock(
        sync_clock=AsyncMock(),
        account=AsyncMock(side_effect=LiveReadError(-2015)),
        listen=AsyncMock(side_effect=AssertionError("authentication not established")),
    )
    monitor = LiveMonitor(Mock(), reader)
    reported = asyncio.Event()

    async def report(status, reason=None):
        assert status == "AUTH_FAILED"
        assert reason == "Binance Live read error (-2015)"
        reported.set()

    monitor.report = report
    task = asyncio.create_task(monitor.run())
    try:
        await asyncio.wait_for(reported.wait(), timeout=2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    reader.listen.assert_not_called()
