"""Authenticated USD-M perpetual prices and admin-managed shared watchlist."""
import asyncio
import json
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from anyio import CancelScope
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from finance_analysis.interfaces.api.v1.schemas.intraday_options_stream import SnapshotStream
from finance_analysis.contracts.service import DAY, cached_candles, key, live_snapshot, now_ms, read_json
from finance_analysis.contracts.underlying import underlying_symbol
from finance_analysis.database.models.contracts import FuturesContract
from finance_analysis.database.repositories import contracts as repository
from finance_analysis.database.repositories.user import UserRepository
from finance_analysis.integrations.crypto.binance import BinanceClient
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.interfaces.api.deps import get_db, require_admin, require_current_user
from finance_analysis.interfaces.api.v1.schemas.contracts import Candle, Contract, ContractCreate, MarketSnapshot
from finance_analysis.interfaces.api.v1.schemas.contracts import ContractFavoriteUpdate, DepthSnapshot, HistoryPage
from finance_analysis.market_stream.config import MarketStreamConfig
from finance_analysis.users.auth import COOKIE_NAME, parse_session_uid

from finance_analysis.database.models.user import User
from finance_analysis.database.models.minute_forecast import MinuteForecastPreference
from finance_analysis.minute_forecast.models import MinuteForecastPreferencePayload, MinuteForecastResponse
from finance_analysis.minute_forecast.cache import latest_forecast
from finance_analysis.minute_forecast.publisher import forecast_url

router = APIRouter()


def realtime():
    return RealtimeStateRepository.from_url(MarketStreamConfig.from_env().redis_url)


async def exchange_contracts():
    client = BinanceClient()
    try:
        return [
            {"symbol": row["symbol"], "category": row["category"],
             "underlying_symbol": underlying_symbol(row["symbol"], row["category"], row["base_asset"])}
            for row in await client.contracts()
        ]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(503, "交易所合约目录暂不可用") from exc
    finally:
        await client.close()


@router.get("/contracts/search", response_model=list[Contract])
async def search(q: str = Query(min_length=1, max_length=32)):
    query = q.upper().strip()
    return [row for row in await exchange_contracts() if query in row["symbol"]][:30]


@router.post("/contracts", response_model=Contract, status_code=201, dependencies=[Depends(require_admin)])
async def add(payload: ContractCreate, db: Session = Depends(get_db)):
    symbol = payload.symbol.upper()
    item = next((row for row in await exchange_contracts() if row["symbol"] == symbol), None)
    if item is None:
        raise HTTPException(422, "仅支持交易中的 USDT 本位永续合约")
    category = (payload.category or item["category"]).strip() or "其他"
    underlying = item["underlying_symbol"]
    db.add(FuturesContract(symbol=symbol, category=category, underlying_symbol=underlying))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "该合约已存在") from exc
    return {"symbol": symbol, "category": category, "underlying_symbol": underlying}


@router.delete("/contracts/{symbol}", status_code=204, dependencies=[Depends(require_admin)])
def delete(symbol: str, db: Session = Depends(get_db)):
    contract = db.get(FuturesContract, symbol, with_for_update=True)
    if contract is None:
        raise HTTPException(404, "合约不存在")
    pref = db.get(MinuteForecastPreference, symbol)
    if pref is not None:
        db.delete(pref)
    db.delete(contract)
    db.commit()


@router.get("/contracts", response_model=MarketSnapshot, response_model_exclude_unset=True)
async def snapshot(symbol: str | None = Query(default=None, max_length=32)):
    store = realtime()
    try:
        return await live_snapshot(store.redis, symbol)
    finally:
        await store.close()


@router.get("/contracts/{symbol}/bars", response_model=list[Candle], response_model_exclude_unset=True)
async def bars(symbol: str, interval: Literal["1m", "1d"] = "1d", include_current: bool = False):
    if symbol not in {row["symbol"] for row in await asyncio.to_thread(repository.contracts)}:
        raise HTTPException(404, "合约不存在")
    history = await asyncio.to_thread(repository.daily, symbol) if interval == "1d" else []
    if interval == "1d" and not include_current:
        return history
    store = realtime()
    try:
        minutes, current = await cached_candles(store.redis, symbol, interval)
        if interval == "1m":
            return minutes or []
        if current and (not history or current["timestamp"] > history[-1]["timestamp"]):
            history.append(current)
        return history
    finally:
        await store.close()


@router.get("/contracts/events")
async def events(request: Request, symbol: str | None = Query(default=None, max_length=32),
                 interval: Literal["1d", "1m"] = "1m", delta: bool = False):
    encode = SnapshotStream().encode if delta else dict

    async def stream():
        store = realtime()
        try:
            while not await request.is_disconnected():
                yield "data: " + json.dumps(encode(await live_snapshot(store.redis, symbol, interval))) + "\n\n"
                await asyncio.sleep(5)
        finally:
            with CancelScope(shield=True):
                await store.close()
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "private, no-store", "X-Accel-Buffering": "no"})


@router.websocket("/contracts/ws")
async def websocket(socket: WebSocket, symbol: str | None = Query(default=None, max_length=32),
                    interval: Literal["1d", "1m"] = "1m", delta: bool = False):
    encode = SnapshotStream().encode if delta else dict
    uid = parse_session_uid(socket.cookies.get(COOKIE_NAME) or "")
    await socket.accept()
    if not uid or not await asyncio.to_thread(lambda: UserRepository().get_by_uid(uid)):
        await socket.close(code=4401, reason="Login required")
        return
    store = realtime()
    try:
        while True:
            await socket.send_json(encode(await live_snapshot(store.redis, symbol, interval)))
            await asyncio.sleep(5)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await store.close()


@router.get("/contracts/{symbol}/metrics", response_model=HistoryPage)
def metrics(symbol: str, start: int = Query(ge=0, le=253402300799999),
            end: int = Query(ge=0, le=253402300799999), limit: int = Query(288, ge=1, le=500)):
    if not 0 <= end - start <= 31 * DAY:
        raise HTTPException(422, "查询范围须在 31 天内")
    rows = repository.metric_history(symbol.upper(), start, end, limit + 1)
    return {"items": rows[:limit], "next_start": rows[limit]["timestamp"] if len(rows) > limit else None}


@router.get("/contracts/{symbol}/depth", response_model=DepthSnapshot | None)
async def depth(symbol: str):
    if symbol not in {row["symbol"] for row in await asyncio.to_thread(repository.contracts)}:
        raise HTTPException(404, "合约不存在")
    store = realtime()
    try:
        # A short interest lease coalesces all viewers; only the leader calls Binance.
        await store.redis.set(key(symbol, "depth-demand"), "1", ex=15)
        item = await read_json(store.redis, key(symbol, "depth"), None)
        return item if item and abs(now_ms() - item["timestamp"]) < 15000 else None
    finally:
        await store.close()


@router.get("/contracts/favorites")
def favorites(user: User = Depends(require_current_user)) -> list[str]:
    return (user.extra or {}).get("contract_favorites", [])


@router.put("/contracts/{symbol}/favorite")
def favorite(symbol: str, payload: ContractFavoriteUpdate, user: User = Depends(require_current_user),
             db: Session = Depends(get_db)) -> list[str]:
    require_contract(db, symbol)
    account = db.get(User, user.id, with_for_update=True)
    symbols = set((account.extra or {}).get("contract_favorites", []))
    if payload.enabled:
        symbols.add(symbol)
    else:
        symbols.discard(symbol)
    result = sorted(symbols)
    account.extra = {**(account.extra or {}), "contract_favorites": result}
    db.commit()
    return result


def require_contract(db, symbol):
    if db.get(FuturesContract, symbol) is None:
        raise HTTPException(404, "合约不存在")


@router.get("/contracts/{symbol}/forecast/preference")
def forecast_preference(symbol: str, db: Session = Depends(get_db)):
    require_contract(db, symbol)
    return MinuteForecastPreferencePayload(enabled=db.get(MinuteForecastPreference, symbol) is not None)


@router.put("/contracts/{symbol}/forecast/preference", dependencies=[Depends(require_admin)])
def set_forecast_preference(symbol: str, payload: MinuteForecastPreferencePayload, db: Session = Depends(get_db)):
    if db.get(FuturesContract, symbol, with_for_update=True) is None:
        raise HTTPException(404, "合约不存在")
    pref = db.get(MinuteForecastPreference, symbol)
    if payload.enabled and pref is None:
        db.add(MinuteForecastPreference(symbol=symbol))
    elif not payload.enabled and pref is not None:
        db.delete(pref)
    db.commit()
    return payload


@router.get("/contracts/{symbol}/forecast", response_model=MinuteForecastResponse)
async def contract_forecast(symbol: str, preference: MinuteForecastPreferencePayload = Depends(forecast_preference)):
    if not forecast_url() or not preference.enabled:
        return MinuteForecastResponse(enabled=False)
    store = realtime()
    try:
        return MinuteForecastResponse(enabled=True, forecast=await latest_forecast(store.redis, symbol))
    finally:
        await store.close()
