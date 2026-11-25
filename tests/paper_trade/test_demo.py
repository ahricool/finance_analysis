import hashlib
import hmac
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from finance_analysis.database.models.paper_trade import (
    PaperStrategy,
    PaperIntent,
    PaperExchangeRecord,
    PaperAccountSnapshot,
    PaperTradeControl,
)
from finance_analysis.database.repositories import paper_trade as repo
from finance_analysis.integrations.crypto.binance_demo import DemoClient, DemoError
from finance_analysis.interfaces.api.deps import require_admin
from finance_analysis.interfaces.api.middlewares.auth import add_auth_middleware
from finance_analysis.interfaces.api.v1.endpoints import paper_trade
from finance_analysis.paper_trade.config import DemoConfig
from finance_analysis.paper_trade.ledger import attributed_trades, ownership, performance
from finance_analysis.paper_trade.runtime import PaperRuntime, order_state
from finance_analysis.paper_trade.strategy import (
    D,
    closed_closes,
    contract_rule,
    ema_cross,
    sized_quantity,
    validate_order,
)

RULE = {
    "symbol": "BTCUSDT",
    "status": "TRADING",
    "contractType": "PERPETUAL",
    "underlyingType": "COIN",
    "marginAsset": "USDT",
    "quoteAsset": "USDT",
    "filters": [
        {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": "0.001"},
        {"filterType": "MARKET_LOT_SIZE", "minQty": "0.001", "maxQty": "50", "stepSize": "0.001"},
        {"filterType": "PRICE_FILTER", "minPrice": "0.1", "maxPrice": "1000000", "tickSize": "0.1"},
        {"filterType": "MIN_NOTIONAL", "notional": "5"},
    ],
}
SYMBOL = "BTCUSDT"


@pytest.fixture
def db_repo(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    for model in (PaperStrategy, PaperIntent, PaperExchangeRecord, PaperAccountSnapshot, PaperTradeControl):
        model.__table__.create(engine)
    factory = sessionmaker(engine)

    @contextmanager
    def session():
        with factory.begin() as s:
            yield s

    monkeypatch.setattr(repo, "session_scope", session)
    yield engine
    engine.dispose()


@pytest.mark.asyncio
async def test_demo_transport_signature_host_algo_and_uncertain_write(caplog):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "demo-fapi.binance.com"
        assert request.headers["X-MBX-APIKEY"] == "mock-key"
        assert "mock-secret" not in str(request.url)
        if request.url.path == "/fapi/v1/listenKey":
            return httpx.Response(200, json={"listenKey": "mock-listen"})
        query, signature = request.url.query.decode().rsplit("&signature=", 1)
        assert signature == hmac.new(b"mock-secret", query.encode(), hashlib.sha256).hexdigest()
        if request.method == "DELETE":
            return httpx.Response(200, json={"code": "200"})
        if request.method == "POST":
            return httpx.Response(503, json={"code": -1007, "msg": "mock-secret"})
        return httpx.Response(200, json={"status": "NEW"})

    client = DemoClient(DemoConfig("mock-key", "mock-secret"), httpx.MockTransport(handler))
    try:
        with pytest.raises(DemoError) as exc:
            await client.submit({"symbol": SYMBOL, "newClientOrderId": "unique"})
        assert exc.value.uncertain and "mock-secret" not in str(exc.value)
        assert len(calls) == 1
        await client.query(SYMBOL, "unique")
        await client.query(SYMBOL, "algo-unique", True)
        await client.cancel(SYMBOL, "123", True)
        await client.listen()
        with pytest.raises(DemoError, match="DEMO_ENDPOINT_NOT_ALLOWED"):
            await client.request("GET", "https://fapi.binance.com/fapi/v3/account")
    finally:
        await client.close()
    assert [r.url.path for r in calls] == [
        "/fapi/v1/order",
        "/fapi/v1/order",
        "/fapi/v1/algoOrder",
        "/fapi/v1/algoOrder",
        "/fapi/v1/listenKey",
    ]
    assert "mock-key" not in caplog.text and "mock-secret" not in caplog.text and "signature=" not in caplog.text


def test_decimal_rules_and_closure():
    assert sized_quantity(RULE, "100", "30000") == D("0.003")
    assert validate_order(RULE, {"type": "LIMIT", "quantity": "0.001", "price": "10000.0"}, "10000") == D("0.001")
    for quantity, price in [("0.0011", "10000"), ("0.001", "10000.01"), ("0.001", "10")]:
        with pytest.raises(ValueError):
            validate_order(RULE, {"type": "LIMIT", "quantity": quantity, "price": price}, "10000")
    with pytest.raises(ValueError):
        contract_rule([RULE], "NOTDEMO")
    end = 300_000 * 100
    bars = [{"timestamp": t, "close": "10"} for t in range(end - 900_000, end + 60_000, 60_000)]
    bars[-1]["close"] = "999999"  # forming minute must never be used
    assert closed_closes(bars, end + 20_000, 3) == (end, [D("10")] * 3)
    assert closed_closes(bars[:-1], end + 20_000, 3) is None
    assert closed_closes(bars[:5] + bars[6:], end + 20_000, 3) is None
    assert closed_closes(bars, end + 100_000, 3) is None
    assert ema_cross([D(10)] * 8 + [D(11)], {"fast": 2, "slow": 4})[0] == "LONG"


def test_durable_signal_pause_idempotency_and_exchange_dedup(db_repo):
    repo.save_strategy(SYMBOL, {"name": "test"})
    paused = repo.signal(SYMBOL, 100, {"direction": "LONG"}, "SIGNAL")
    assert paused["status"] == "OBSERVED"
    assert repo.signal(SYMBOL, 100, {}, "SIGNAL") is None
    repo.set_trade_control(True)
    repo.control(SYMBOL, True)
    bar = repo.strategies()[0]["cursor"] + 300_000
    queued = repo.signal(SYMBOL, bar, {}, "SIGNAL")
    assert queued["status"] == "QUEUED"
    repo.control(SYMBOL, False)
    assert not repo.intents(True)
    repo.control(SYMBOL, True)
    bar = repo.strategies()[0]["cursor"] + 600_000
    queued = repo.signal(SYMBOL, bar, {}, "SIGNAL")
    repo.skip_previous_bars(bar)
    assert not repo.intents(True)
    request_id = uuid4().hex
    repo.queue(request_id, SYMBOL, "MANUAL", {"quantity": "1"})
    repo.transition(request_id, "SUBMITTING", None, {"quantity": "1", "algo": False, "exchange_request": {}})
    assert repo.queue(request_id, SYMBOL, "MANUAL", {"quantity": "1"})["status"] == "SUBMITTING"
    trade = {"symbol": SYMBOL, "id": 12, "orderId": 1, "time": 123}
    repo.put_records("trade", [trade, trade])
    assert len(repo.records("trade")) == 1
    repo.put_records("order", [{"symbol": SYMBOL, "orderId": 1, "updateTime": 5, "status": "FILLED"}])
    repo.put_records("order", [{"symbol": SYMBOL, "orderId": 1, "updateTime": 4, "status": "NEW"}])
    assert repo.records("order")[0]["status"] == "FILLED"
    assert order_state({"algoStatus": "FINISHED"}, True) == "FINISHED"
    assert order_state({"status": "PARTIALLY_FILLED"}, False) == "PARTIALLY_FILLED"
    assert "futures_contract" not in inspect(db_repo).get_table_names()


def test_attribution_conflicts_profit_and_funding():
    intents = [
        {
            "id": "a",
            "symbol": SYMBOL,
            "strategy": SYMBOL,
            "action": "SIGNAL",
            "payload": {"exchange_request": {"symbol": SYMBOL}},
        },
        {
            "id": "b",
            "symbol": SYMBOL,
            "strategy": SYMBOL,
            "action": "PROTECT",
            "payload": {"exchange_request": {"symbol": SYMBOL}},
        },
    ]
    orders = [{"symbol": SYMBOL, "orderId": 1, "clientOrderId": "a"}]
    algos = [{"symbol": SYMBOL, "algoId": 5, "actualOrderId": "2", "clientAlgoId": "b"}]
    base = {"symbol": SYMBOL, "qty": "1", "commission": "0.1", "commissionAsset": "USDT", "realizedPnl": "0"}
    opening = {**base, "orderId": 1, "id": 1, "time": 100, "side": "BUY"}
    closing = {**base, "orderId": 2, "id": 2, "time": 300, "side": "SELL", "realizedPnl": "5"}
    external = {**base, "orderId": 3, "id": 3, "time": 200, "side": "BUY"}
    own = attributed_trades(intents, orders, algos, [opening, closing])
    assert all(row["strategy"] == SYMBOL for row in own)
    pos = [{"symbol": SYMBOL, "positionAmt": "1"}]
    assert ownership(SYMBOL, pos, own[:1]) == (D(1), True, False)
    assert ownership(SYMBOL, pos, []) == (D(1), False, True)
    income = [{"symbol": SYMBOL, "time": 200, "incomeType": "FUNDING_FEE", "asset": "USDT", "income": "-0.2"}]
    assert performance(SYMBOL, own, income)["net"] == "4.6"
    assert performance(SYMBOL, own, income)["average_hold_ms"] == 200
    contaminated = attributed_trades(intents, orders, algos, [opening, external, closing])
    assert performance(SYMBOL, contaminated, income)["net"] is None


def test_admin_only_and_disabled_snapshot(monkeypatch, db_repo):
    monkeypatch.setenv("BINANCE_DEMO_API_KEY", "")
    monkeypatch.setenv("BINANCE_DEMO_API_SECRET", "")
    app = FastAPI()
    app.include_router(paper_trade.router, prefix="/api/v1/crypto/paper-trade")
    add_auth_middleware(app)
    with TestClient(app) as client:
        assert client.get("/api/v1/crypto/paper-trade").status_code == 401
    app = FastAPI()
    app.include_router(paper_trade.router, prefix="/api/v1/crypto/paper-trade")

    def non_admin():
        raise HTTPException(403, "admin required")

    app.dependency_overrides[require_admin] = non_admin
    with TestClient(app) as client:
        assert client.get("/api/v1/crypto/paper-trade").status_code == 403
        assert client.post("/api/v1/crypto/paper-trade/orders", json={}).status_code == 403
    app.dependency_overrides[require_admin] = lambda: object()
    with TestClient(app) as client:
        result = client.get("/api/v1/crypto/paper-trade").json()
        assert result["connection"]["status"] == "NOT_CONFIGURED"
        assert result["view"] is None and result["realized_net"] is None


@pytest.mark.asyncio
async def test_submission_uncertain_never_retried_and_manual_conflict(db_repo):
    from finance_analysis.paper_trade.runtime import now_ms

    fake = Mock(
        quote=AsyncMock(return_value={"time": now_ms(), "price": "10000"}),
        positions=AsyncMock(return_value=[]),
        submit=AsyncMock(side_effect=DemoError(-1007, uncertain=True)),
    )
    leader = Mock(renew=AsyncMock(return_value=True))
    runtime = PaperRuntime(Mock(), fake, leader)
    runtime.rules = [RULE]
    runtime.view = {
        "positions": [],
        "configuration": {"dualSidePosition": False, "canTrade": True},
        "sync_started": now_ms(),
        "open_orders": [],
        "open_algos": [],
    }
    payload = {"order_type": "MARKET", "side": "BUY", "quantity": "0.001", "reduce_only": False}
    repo.set_trade_control(True)
    intent = repo.queue(uuid4().hex, SYMBOL, "MANUAL", payload)
    # SQLite fixture omits timezone; normalize to UTC for timestamps.
    intent["created_at"] = datetime.now(timezone.utc).isoformat()
    await runtime.submit(intent, [])
    assert repo.intents(True)[0]["status"] == "UNKNOWN"
    second = repo.queue(uuid4().hex, SYMBOL, "MANUAL", payload)
    second["created_at"] = datetime.now(timezone.utc).isoformat()
    await runtime.submit(second, [])
    assert fake.submit.await_count == 1
    assert repo.intents()[-1]["reason"] == "UNRESOLVED_ORDER"


@pytest.mark.asyncio
async def test_reconcile_normal_algo_stream_and_app_records(db_repo, monkeypatch):
    from finance_analysis.paper_trade.runtime import now_ms
    from finance_analysis.database.repositories import contracts

    monkeypatch.setattr(contracts, "contracts", lambda: [{"symbol": SYMBOL, "category": "COIN"}])
    timestamp = now_ms() - 1000
    normal = []
    algo_orders = []
    fills = []
    positions = []
    income = []
    posted = []
    submits = []
    alias = "test-account"
    account = {"totalMarginBalance": "1000", "totalWalletBalance": "1000", "availableBalance": "900"}

    def handler(request):
        assert request.url.host == "demo-fapi.binance.com"
        path, method, params = request.url.path, request.method, request.url.params
        read = {
            "/fapi/v1/time": {"serverTime": now_ms()},
            "/fapi/v3/account": account,
            "/fapi/v3/balance": [{"accountAlias": alias, "asset": "USDT", "balance": "1000"}],
            "/fapi/v3/positionRisk": positions,
            "/fapi/v1/accountConfig": {"dualSidePosition": False, "canTrade": True},
            "/fapi/v1/symbolConfig": [{"symbol": SYMBOL, "leverage": 2, "marginType": "ISOLATED"}],
            "/fapi/v1/exchangeInfo": {"symbols": [RULE]},
            "/fapi/v1/openOrders": [r for r in normal if r["status"] in {"NEW", "PARTIALLY_FILLED"}],
            "/fapi/v1/openAlgoOrders": [r for r in algo_orders if r["algoStatus"] == "NEW"],
            "/fapi/v1/allOrders": normal,
            "/fapi/v1/allAlgoOrders": algo_orders,
            "/fapi/v1/userTrades": fills,
            "/fapi/v1/income": income,
            "/fapi/v2/ticker/price": {"price": "10000", "time": now_ms()},
            "/fapi/v1/premiumIndex": {"lastFundingRate": "0.0001", "nextFundingTime": now_ms() + 1000},
        }
        if path == "/fapi/v1/order":
            if method == "POST":
                submits.append(params["newClientOrderId"])
                record = {
                    "symbol": SYMBOL,
                    "orderId": len(normal) + 100,
                    "clientOrderId": submits[-1],
                    "status": "NEW",
                    "side": params["side"],
                    "type": params["type"],
                    "time": timestamp,
                    "updateTime": timestamp,
                    "origQty": params["quantity"],
                    "executedQty": "0",
                    "price": "0",
                }
                normal.append(record)
                return httpx.Response(200, json=record)
            if method == "DELETE":
                record = next(r for r in normal if str(r["orderId"]) == params["orderId"])
                record.update(status="CANCELED", updateTime=record["updateTime"] + 1)
                return httpx.Response(200, json=record)
            return httpx.Response(
                200, json=next(r for r in normal if r["clientOrderId"] == params["origClientOrderId"])
            )
        if path == "/fapi/v1/algoOrder":
            if method == "POST":
                posted.append(params["clientAlgoId"])
                record = {
                    "symbol": SYMBOL,
                    "clientAlgoId": posted[-1],
                    "algoId": 10,
                    "algoStatus": "NEW",
                    "quantity": params["quantity"],
                    "triggerPrice": params["triggerPrice"],
                    "createTime": timestamp,
                    "updateTime": timestamp,
                    "actualOrderId": "",
                }
                algo_orders.append(record)
                return httpx.Response(200, json=record)
            return httpx.Response(200, json=next(r for r in algo_orders if r["clientAlgoId"] == params["clientAlgoId"]))
        assert path in read, path
        return httpx.Response(200, json=read[path])

    client = DemoClient(DemoConfig("test-key", "test-secret"), httpx.MockTransport(handler))
    runtime = PaperRuntime(Mock(), client, Mock(renew=AsyncMock(return_value=True)))
    cfg = {
        "name": "EMA",
        "symbol": SYMBOL,
        "strategy_type": "ema_cross",
        "direction": "BOTH",
        "fast": 2,
        "slow": 4,
        "notional": "20",
        "margin": "10",
        "max_position": "20",
        "leverage_limit": 2,
        "max_loss": "5",
        "stop_pct": "2",
    }
    try:
        trades, _ = await runtime.sync()
        assert runtime.view["account"]["totalMarginBalance"] == "1000"
        assert not submits and not posted
        repo.save_strategy(SYMBOL, cfg)
        repo.set_trade_control(True)
        repo.control(SYMBOL, True)
        intent = repo.queue(uuid4().hex, SYMBOL, "SIGNAL", {"direction": "LONG", "production_close": "10000"}, SYMBOL)
        await runtime.submit(intent, trades)
        assert repo.intents()[0]["status"] == "SUBMITTED"
        assert len(submits) == 1
        # Crash after exchange ACK, before the process records it as submitted.
        repo.transition(intent["id"], "SUBMITTING")
        runtime = PaperRuntime(Mock(), client, Mock(renew=AsyncMock(return_value=True)))
        await runtime.sync()
        assert repo.intents()[0]["status"] == "SUBMITTED" and len(submits) == 1
        # A partial exchange fill. WS event and REST duplicate the same trade ID.
        normal[0].update(status="PARTIALLY_FILLED", executedQty="0.001", updateTime=timestamp + 1)
        positions[:] = [
            {
                "symbol": SYMBOL,
                "positionSide": "BOTH",
                "positionAmt": "0.001",
                "entryPrice": "10000",
                "markPrice": "10000",
                "unRealizedProfit": "0",
            }
        ]
        event = {
            "e": "ORDER_TRADE_UPDATE",
            "T": timestamp + 1,
            "o": {
                "s": SYMBOL,
                "i": 100,
                "c": submits[0],
                "S": "BUY",
                "o": "MARKET",
                "X": "PARTIALLY_FILLED",
                "q": "0.002",
                "z": "0.001",
                "p": "0",
                "ap": "10000",
                "ps": "BOTH",
                "R": False,
                "x": "TRADE",
                "l": "0.001",
                "N": "USDT",
                "n": "0.01",
                "t": 123,
                "L": "10000",
                "rp": "0",
                "T": timestamp + 1,
            },
        }
        fill = {
            "symbol": SYMBOL,
            "id": 123,
            "orderId": 100,
            "side": "BUY",
            "qty": "0.001",
            "price": "10000",
            "realizedPnl": "0",
            "commission": "0.01",
            "commissionAsset": "USDT",
            "time": timestamp + 1,
        }
        fills.append(fill)
        await runtime.stream_event(event)
        await runtime.stream_event(event)
        trades, _ = await runtime.sync()
        assert len(trades) == 1 and trades[0]["strategy"] == SYMBOL
        assert repo.intents()[0]["status"] == "PARTIALLY_FILLED"
        assert runtime.view["positions"][0]["source"] == "STRATEGY"
        assert runtime.view["positions"][0]["fundingRate"] == "0.0001"
        # Remaining quantity canceled at the exchange; partial position remains owned.
        normal[0].update(status="CANCELED", updateTime=timestamp + 2)
        trades, _ = await runtime.sync()
        assert repo.intents()[0]["status"] == "CANCELED"
        # Protective stop can be placed while paused; it is an independent Algo order.
        repo.control(SYMBOL, False)
        stop = repo.queue(uuid4().hex, SYMBOL, "PROTECT", {}, SYMBOL)
        await runtime.submit(stop, trades)
        assert len(posted) == 1 and repo.intents()[-1]["status"] == "SUBMITTED"
        algo_orders[0].update(algoStatus="FINISHED", actualOrderId="444", updateTime=timestamp + 4)
        normal.append(
            {
                "symbol": SYMBOL,
                "orderId": 444,
                "clientOrderId": "child",
                "status": "FILLED",
                "updateTime": timestamp + 4,
            }
        )
        fills.append({**fill, "id": 124, "orderId": 444, "side": "SELL", "realizedPnl": "-0.2", "time": timestamp + 4})
        positions.clear()
        income.append(
            {
                "symbol": SYMBOL,
                "incomeType": "FUNDING_FEE",
                "tranId": 3,
                "time": timestamp + 3,
                "asset": "USDT",
                "income": "-0.05",
            }
        )
        trades, incomes = await runtime.sync()
        assert len(trades) == 2 and trades[-1]["strategy"] == SYMBOL
        assert repo.intents()[-1]["status"] == "FILLED"
        assert performance(SYMBOL, trades, incomes)["net"] == "-0.27"
        # App-placed orders/positions are external and never taken over as FA.
        normal.append(
            {
                "symbol": SYMBOL,
                "orderId": 888,
                "clientOrderId": "app-manual",
                "status": "FILLED",
                "updateTime": timestamp + 5,
            }
        )
        fills.append({**fill, "id": 125, "orderId": 888, "time": timestamp + 5})
        positions[:] = [
            {
                "symbol": SYMBOL,
                "positionSide": "BOTH",
                "positionAmt": "0.001",
                "entryPrice": "10000",
                "markPrice": "10000",
                "unRealizedProfit": "0",
            }
        ]
        trades, _ = await runtime.sync()
        assert trades[-1]["source"] == "EXTERNAL" and runtime.view["positions"][0]["source"] == "CONFLICT"
        assert len(submits) == 1 and len(posted) == 1
        # A different account must not be merged with the first account's ledger.
        alias = "other-account"
        with pytest.raises(ValueError, match="DEMO_ACCOUNT_CHANGED"):
            await runtime.sync()
        assert repo.snapshots()[0]["account_alias"] == "test-account"
    finally:
        await client.close()


def test_migration_upgrade_downgrade_keeps_contract_watchlist():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    # The repository's alembic folder isn't a Python package.
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parents[2] / "alembic" / "versions" / "0097_paper_trade.py"
    spec = importlib.util.spec_from_file_location("paper_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE futures_contract (symbol TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO futures_contract VALUES ('BTCUSDT')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        for model in (PaperStrategy, PaperIntent, PaperExchangeRecord, PaperAccountSnapshot):
            actual = {c["name"] for c in inspect(connection).get_columns(model.__tablename__)}
            assert actual == set(model.__table__.columns.keys())
        migration.downgrade()
        assert inspect(connection).get_table_names() == ["futures_contract"]
        assert connection.execute(text("SELECT symbol FROM futures_contract")).scalar() == SYMBOL
    engine.dispose()


def test_pause_allows_existing_position_exit_but_not_new_entries(db_repo):
    repo.save_strategy(SYMBOL, {"name": "test"})
    exit_signal = repo.signal(SYMBOL, 100, {"direction": "SHORT"}, "CLOSE")
    assert exit_signal["status"] == "QUEUED"
    opening = repo.signal(SYMBOL, 200, {"direction": "LONG"}, "SIGNAL")
    assert opening["status"] == "OBSERVED"
    assert not repo.claim(opening["id"], SYMBOL, "SIGNAL", {})


@pytest.mark.asyncio
async def test_missing_credentials_never_constructs_private_client(monkeypatch):
    from finance_analysis.paper_trade import runtime

    monkeypatch.setenv("BINANCE_DEMO_API_KEY", "")
    monkeypatch.setenv("BINANCE_DEMO_API_SECRET", "")
    constructor = Mock(side_effect=AssertionError("Must not create client"))
    monkeypatch.setattr(runtime, "DemoClient", constructor)
    assert DemoConfig.from_env().status == "NOT_CONFIGURED"
    await runtime.run_paper_trade(Mock(), Mock())
    constructor.assert_not_called()


def test_global_demo_switch_blocks_opening_and_keeps_management(db_repo):
    assert repo.trade_control() == {"enabled": False, "updated_at": None}
    with pytest.raises(ValueError, match="GLOBAL_TRADING_DISABLED"):
        repo.queue(uuid4().hex, SYMBOL, "MANUAL", {"reduce_only": False})
    closing = repo.queue(uuid4().hex, SYMBOL, "CLOSE", {})
    assert closing["status"] == "QUEUED"
    repo.set_trade_control(True)
    opening = repo.queue(uuid4().hex, SYMBOL, "MANUAL", {"reduce_only": False})
    repo.set_trade_control(False)
    assert not repo.claim(opening["id"], SYMBOL, "MANUAL", {"reduce_only": False})
    assert repo.claim(closing["id"], SYMBOL, "CLOSE", {})
    assert repo.trade_control()["enabled"] is False


def test_account_binding_before_first_snapshot_and_identity_isolation(db_repo):
    repo.bind_account("first")
    assert repo.snapshots()[0] is None
    repo.put_records("order", [{"symbol": SYMBOL, "orderId": 9, "time": 1, "status": "NEW"}])
    with pytest.raises(ValueError, match="DEMO_ACCOUNT_CHANGED"):
        repo.bind_account("other")
    assert repo.records("order")[0]["orderId"] == "9"
    repo.bind_account("first")


def test_attribution_requires_claim_and_symbol_and_hedge_never_owned():
    from finance_analysis.paper_trade.ledger import attribution

    intents = [
        {"id": "queued", "symbol": SYMBOL, "action": "SIGNAL", "payload": {}},
        {
            "id": "claimed",
            "symbol": "ETHUSDT",
            "action": "SIGNAL",
            "payload": {"exchange_request": {"symbol": "ETHUSDT"}},
        },
    ]
    assert (
        attribution(
            intents,
            [
                {"symbol": SYMBOL, "orderId": 1, "clientOrderId": "queued"},
                {"symbol": SYMBOL, "orderId": 2, "clientOrderId": "claimed"},
            ],
            [],
        )
        == {}
    )
    assert ownership(
        SYMBOL,
        [
            {"symbol": SYMBOL, "positionAmt": "1", "positionSide": "LONG"},
            {"symbol": SYMBOL, "positionAmt": "-1", "positionSide": "SHORT"},
        ],
        [],
    ) == (D(0), False, True)


def test_close_requires_the_displayed_position_snapshot(monkeypatch, db_repo):
    async def connection():
        return {
            "positions": [
                {
                    "symbol": SYMBOL,
                    "positionAmt": "0.002",
                    "entryPrice": "10000",
                    "positionSide": "BOTH",
                    "source": "EXTERNAL",
                }
            ]
        }

    monkeypatch.setattr(paper_trade, "require_connection", connection)
    app = FastAPI()
    app.include_router(paper_trade.router, prefix="/api/v1/crypto/paper-trade")
    app.dependency_overrides[require_admin] = lambda: object()
    with TestClient(app) as client:
        base = "/api/v1/crypto/paper-trade"
        payload = {"request_id": str(uuid4()), "symbol": SYMBOL, "confirm_demo": True, "position_side": "BOTH"}
        assert client.post(base + "/close", json=payload).status_code == 422
        assert client.post(base + "/close", json={**payload, "expected_quantity": "0.001"}).status_code == 409
        assert (
            client.post(
                base + "/close", json={**payload, "expected_quantity": "0.002", "expected_entry_price": "9900"}
            ).status_code
            == 409
        )
        result = client.post(
            base + "/close", json={**payload, "expected_quantity": "0.002", "expected_entry_price": "10000"}
        )
        assert result.status_code == 202
        assert len(repo.intents()) == 1
        assert result.headers["Cache-Control"] == "private, no-store"


def test_global_control_migration_matches_schema():
    import importlib.util
    from pathlib import Path
    from alembic.operations import Operations
    from alembic.migration import MigrationContext

    path = Path(__file__).parents[2] / "alembic" / "versions" / "0099_paper_control.py"
    spec = importlib.util.spec_from_file_location("paper_control_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        assert {c["name"] for c in inspect(conn).get_columns(PaperTradeControl.__tablename__)} == set(
            PaperTradeControl.__table__.columns.keys()
        )
        migration.downgrade()
        assert not inspect(conn).has_table(PaperTradeControl.__tablename__)
    engine.dispose()


def test_reconcile_order_candidates_retained_after_partial_snapshot():
    from finance_analysis.integrations.crypto.account_records import reconciliation_orders

    old = {"symbol": SYMBOL, "orderId": "100", "clientOrderId": "old"}
    new = {"symbol": SYMBOL, "algoId": "100", "clientAlgoId": "new"}
    partial = {"reconcile_open_orders": [old], "open_orders": [], "open_algos": [new]}
    assert reconciliation_orders(partial) == [old, new]
