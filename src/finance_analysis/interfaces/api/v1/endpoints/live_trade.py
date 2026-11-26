"""Admin-only read-only Live account data and local switch. No order endpoints."""

import asyncio
import json
from decimal import Decimal

from fastapi import APIRouter, Depends
from redis.exceptions import RedisError

from finance_analysis.database.repositories import live_trade as repo
from finance_analysis.interfaces.api.deps import require_admin, private_no_store
from finance_analysis.interfaces.api.v1.schemas.live_trade import LiveControl, LiveControlUpdate, LiveSnapshot
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.market_stream.config import MarketStreamConfig
from finance_analysis.crypto_strategy.observe import OBSERVATION_KEY
from finance_analysis.live_trade.config import LiveConfig
from finance_analysis.live_trade.gateway import STRATEGIES
from finance_analysis.live_trade.runtime import STATUS_KEY

router = APIRouter(dependencies=[Depends(require_admin), Depends(private_no_store)])


async def connection():
    if not LiveConfig.from_env().configured:
        return {"status": "NOT_CONFIGURED", "stream_connected": False}
    store = RealtimeStateRepository.from_url(MarketStreamConfig.from_env().redis_url)
    try:
        value, observation = await store.redis.mget([STATUS_KEY, OBSERVATION_KEY])
        result = json.loads(value) if value else {"status": "WAITING", "stream_connected": False}
        result["observation"] = json.loads(observation) if observation else None
        return result
    except RedisError:
        return {"status": "UNAVAILABLE", "stream_connected": False}
    finally:
        await store.close()


def data():
    view, equity = repo.snapshots()
    orders, algos, trades, income = [repo.records(kind) for kind in ("order", "algo", "trade", "income")]
    for record in orders + algos + trades:
        record["source"] = "EXTERNAL"
    net = sum(
        (
            Decimal(r["income"])
            for r in income
            if r.get("asset") == "USDT" and r.get("incomeType") in {"REALIZED_PNL", "COMMISSION", "FUNDING_FEE"}
        ),
        Decimal(0),
    )
    return {
        "environment": "LIVE",
        "control": repo.control(),
        "view": view,
        "equity": equity,
        "orders": orders,
        "algos": algos,
        "trades": trades,
        "income": income,
        "realized_net": str(net) if view and view.get("complete") else None,
        "control_events": repo.events(),
        "strategy_count": len(STRATEGIES),
    }


@router.get("", response_model=LiveSnapshot)
async def snapshot():
    result = await asyncio.to_thread(data)
    result["connection"] = await connection()
    return result


@router.get("/control", response_model=LiveControl)
def control():
    return repo.control()


@router.put("/control", response_model=LiveControl)
def update_control(payload: LiveControlUpdate, user=Depends(require_admin)):
    return repo.set_control(payload.enabled, user.id)
