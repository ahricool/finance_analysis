"""Admin-only Demo controls. GET never contacts the exchange or executes orders."""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from redis.exceptions import RedisError

from finance_analysis.database.repositories import paper_trade as repo
from finance_analysis.interfaces.api.deps import require_admin, private_no_store
from finance_analysis.interfaces.api.v1.schemas.paper_trade import (
    OrderAction,
    ClosePosition,
    PaperSnapshot,
    PaperTradeControl,
    StrategyControl,
)
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.market_stream.config import MarketStreamConfig
from finance_analysis.paper_trade.config import DemoConfig
from finance_analysis.paper_trade.ledger import (
    attribution,
    attributed_trades,
    claimed_intents,
    intent_owner,
    performance,
)
from finance_analysis.paper_trade.runtime import STATUS_KEY, ms, now_ms
from finance_analysis.paper_trade.strategy import D

router = APIRouter(dependencies=[Depends(require_admin), Depends(private_no_store)])


async def connection():
    config = DemoConfig.from_env()
    if config.status != "CONFIGURED":
        return {"status": config.status, "stream_connected": False}
    store = RealtimeStateRepository.from_url(MarketStreamConfig.from_env().redis_url)
    try:
        value = await store.redis.get(STATUS_KEY)
        return json.loads(value) if value else {"status": "WAITING", "stream_connected": False}
    except RedisError:
        return {"status": "UNAVAILABLE", "stream_connected": False}
    finally:
        await store.close()


def data():
    view, equity = repo.snapshots()
    requests = repo.intents()
    orders, algos, trades, income = [repo.records(k) for k in ("order", "algo", "trade", "income")]
    trades = attributed_trades(requests, orders, algos, trades)
    strategies = repo.strategies()
    client_ids = claimed_intents(requests)
    linked = attribution(requests, orders, algos)
    for row in orders + algos:
        owner = intent_owner(client_ids, row, "clientAlgoId" if "algoId" in row else "clientOrderId")
        if not owner and row.get("orderId"):
            owner = linked.get((row["symbol"], str(row["orderId"])))
        row["source"] = "STRATEGY" if owner and owner["strategy"] else "FA_MANUAL" if owner else "EXTERNAL"
    for s in strategies:
        s["performance"] = performance(s["symbol"], trades, income, s.get("strategy_type", "ema_cross"))
        stats = s["performance"]
        stats["win_rate_pct"] = (
            str((D(stats["win_rate"]) * 100).quantize(D("0.01"))) if stats["win_rate"] is not None else None
        )
        stats["average_hold_minutes"] = (
            str((D(stats["average_hold_ms"]) / 60_000).quantize(D("0.01")))
            if stats["average_hold_ms"] is not None
            else None
        )
        config = next((r for r in (view or {}).get("symbol_config", []) if r["symbol"] == s["symbol"]), {})
        s["current_leverage"] = config.get("leverage")
        s["current_margin_type"] = config.get("marginType")
        s["latest_signal"] = next(
            (i for i in reversed(requests) if i["strategy"] == s["symbol"] and i["bar_time"]), None
        )
        s["latest_trade"] = next((t for t in reversed(trades) if t["strategy"] == s["symbol"]), None)
    net = sum(
        (
            D(r["income"])
            for r in income
            if r["incomeType"] in {"REALIZED_PNL", "COMMISSION", "FUNDING_FEE"} and r["asset"] == "USDT"
        ),
        D(0),
    )
    return {
        "trade_control": repo.trade_control(),
        "view": view,
        "equity": equity,
        "strategies": strategies,
        "intents": list(reversed(requests)),
        "orders": list(reversed(orders)),
        "algos": list(reversed(algos)),
        "trades": list(reversed(trades)),
        "income": list(reversed(income)),
        "realized_net": str(net) if view and view.get("complete") else None,
    }


@router.get("", response_model=PaperSnapshot)
async def snapshot():
    result = await asyncio.to_thread(data)
    result["connection"] = await connection()
    return result


def mutation(fn, *args):
    try:
        return fn(*args)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


async def require_connection():
    view, _ = await asyncio.to_thread(repo.snapshots)
    if (
        (await connection())["status"] != "CONNECTED"
        or not view
        or not view.get("complete")
        or now_ms() - ms(view["synced_at"]) > 90_000
    ):
        raise HTTPException(503, "Demo 未连接或核对未完成")
    return view


@router.get("/control", response_model=PaperTradeControl)
def global_control():
    return repo.trade_control()


@router.put("/control", response_model=PaperTradeControl)
async def update_global_control(payload: StrategyControl):
    if payload.enabled:
        await require_connection()
    return await asyncio.to_thread(repo.set_trade_control, payload.enabled)


@router.post("/cancel", status_code=202)
async def cancel(payload: OrderAction):
    await require_connection()
    if payload.exchange_id is None:
        raise HTTPException(422, "缺少交易所订单 ID")
    return await asyncio.to_thread(
        mutation,
        repo.queue,
        payload.request_id.hex,
        payload.symbol,
        "CANCEL",
        {"algo": payload.algo, "exchange_id": payload.exchange_id},
    )


@router.post("/close", status_code=202)
async def close(payload: ClosePosition):
    view = await require_connection()
    if payload.position_side != "BOTH":
        raise HTTPException(422, "目前仅支持单向持仓模式")
    position = next(
        (
            p
            for p in (view or {}).get("positions", [])
            if p["symbol"] == payload.symbol and p["positionSide"] == payload.position_side
        ),
        None,
    )
    if not position:
        raise HTTPException(409, "当前无持仓")
    if D(position["positionAmt"]) != payload.expected_quantity or (
        payload.expected_entry_price is not None and D(position["entryPrice"]) != payload.expected_entry_price
    ):
        raise HTTPException(409, "持仓已变化，请刷新后重新确认")
    strategy = payload.symbol if position.get("source") == "STRATEGY" else None
    if strategy:
        await asyncio.to_thread(repo.control, strategy, False)
    return await asyncio.to_thread(
        mutation,
        repo.queue,
        payload.request_id.hex,
        payload.symbol,
        "CLOSE",
        {
            "expected_quantity": str(payload.expected_quantity),
            "expected_entry_price": (
                str(payload.expected_entry_price) if payload.expected_entry_price is not None else None
            ),
        },
        strategy,
    )
