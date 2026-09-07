"""Authenticated BTC transport; all data access goes through CryptoService."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from finance_analysis.crypto.realtime import CryptoRealtime
from finance_analysis.crypto.service import CryptoService
from finance_analysis.database.config import get_database_config
from finance_analysis.database.repositories.user import UserRepository
from finance_analysis.interfaces.api.v1.schemas.crypto import (
    CryptoKlinesResponse,
    CryptoOverviewResponse,
    CryptoRealtimeResponse,
    CryptoSignalsResponse,
    CryptoStatusResponse,
)
from finance_analysis.users.auth import COOKIE_NAME, parse_session_uid

router = APIRouter()


async def get_crypto_service():
    realtime = CryptoRealtime.from_url(get_database_config().redis_url)
    try:
        # Database bootstrap is synchronous; keep it off the event loop.
        service = await asyncio.to_thread(CryptoService, realtime=realtime)
        yield service
    finally:
        await realtime.close()


@router.get("/btc/overview", response_model=CryptoOverviewResponse)
async def overview(service: CryptoService = Depends(get_crypto_service)):
    return await service.get_overview()


@router.get("/btc/klines", response_model=CryptoKlinesResponse)
async def klines(
    interval: Literal["1m"] = "1m",
    limit: int = Query(1000, ge=1, le=1000),
    service: CryptoService = Depends(get_crypto_service),
):
    return {"items": await asyncio.to_thread(service.get_recent_klines, limit)}


@router.get("/btc/signals", response_model=CryptoSignalsResponse)
async def signals(limit: int = Query(50, ge=1, le=200), service: CryptoService = Depends(get_crypto_service)):
    return {"items": await asyncio.to_thread(service.get_signals, limit)}


@router.get("/btc/status", response_model=CryptoStatusResponse)
async def status(service: CryptoService = Depends(get_crypto_service)):
    return await service.get_market_state()


def _valid_user(token):
    uid = parse_session_uid(token or "")
    return uid is not None and UserRepository().get_by_uid(uid) is not None


@router.websocket("/ws")
async def realtime(websocket: WebSocket):
    # HTTP auth middleware does not run on WebSockets.
    token = websocket.cookies.get(COOKIE_NAME)
    if not await asyncio.to_thread(_valid_user, token):
        await websocket.accept()
        await websocket.close(code=4401, reason="Login required")
        return
    await websocket.accept()
    cache = CryptoRealtime.from_url(get_database_config().redis_url)
    try:
        service = await asyncio.to_thread(CryptoService, realtime=cache)
        while True:
            if not await asyncio.to_thread(_valid_user, token):
                await websocket.close(code=4401, reason="Session expired")
                return
            payload = CryptoRealtimeResponse(market=await service.get_market_state())
            await websocket.send_text(payload.model_dump_json())
            try:
                # Also observe disconnects promptly; no client subscription protocol in V0.1.
                await asyncio.wait_for(websocket.receive_text(), timeout=2)
            except TimeoutError:
                pass
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await cache.close()
