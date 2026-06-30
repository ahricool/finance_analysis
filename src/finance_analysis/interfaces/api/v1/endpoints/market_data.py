"""Authenticated WebSocket stream for user-scoped realtime market quotes."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Iterable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from finance_analysis.core.time import utc_isoformat, utc_now
from finance_analysis.database.config import get_database_config
from finance_analysis.database.repositories.stock_list import StockListRepo
from finance_analysis.database.repositories.user import UserRepository
from finance_analysis.database.repositories.watch_list import WatchListRepo
from finance_analysis.integrations.market_data.providers.longbridge.market import _to_longbridge_symbol
from finance_analysis.integrations.market_data.realtime_state.models import QuoteState
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.users.auth import COOKIE_NAME, parse_session_uid

logger = logging.getLogger(__name__)
router = APIRouter()
PUSH_INTERVAL_SECONDS = 5


@dataclass(frozen=True, slots=True)
class TrackedStock:
    code: str
    market_type: str
    symbol: str


def _load_tracked_stocks(uid: int) -> list[TrackedStock]:
    items: Iterable[Any] = [
        *WatchListRepo().list_all(uid=uid),
        *StockListRepo().list_all(uid=uid),
    ]
    tracked: dict[tuple[str, str], TrackedStock] = {}
    for item in items:
        code = str(item.code).strip().upper()
        market_type = str(item.market_type).strip().upper()
        try:
            symbol = _to_longbridge_symbol(code)
        except Exception as exc:
            logger.warning("无法转换实时行情代码: code=%s market=%s error=%s", code, market_type, exc)
            continue
        if symbol:
            tracked[(market_type, code)] = TrackedStock(code=code, market_type=market_type, symbol=symbol)
    return list(tracked.values())


def _user_exists(uid: int) -> bool:
    return UserRepository().get_by_uid(uid) is not None


def _number(value: Decimal | int | None) -> float | int | None:
    if value is None:
        return None
    return int(value) if isinstance(value, int) else float(value)


def _quote_payload(stock: TrackedStock, quote: QuoteState | None) -> dict[str, Any]:
    base: dict[str, Any] = {**asdict(stock), "available": quote is not None}
    if quote is None:
        return base

    change_amount: Decimal | None = None
    change_pct: Decimal | None = None
    if quote.last_price is not None and quote.pre_close is not None:
        change_amount = quote.last_price - quote.pre_close
        if quote.pre_close:
            change_pct = change_amount / quote.pre_close * Decimal("100")

    return {
        **base,
        "last_price": _number(quote.last_price),
        "change_amount": _number(change_amount),
        "change_pct": _number(change_pct),
        "open": _number(quote.open),
        "high": _number(quote.high),
        "low": _number(quote.low),
        "pre_close": _number(quote.pre_close),
        "volume": quote.volume,
        "turnover": _number(quote.turnover),
        "trade_session": quote.trade_session,
        "event_time": utc_isoformat(quote.event_time),
        "received_at": utc_isoformat(quote.received_at),
    }


async def _build_snapshot(uid: int, repository: RealtimeStateRepository) -> dict[str, Any]:
    stocks = await asyncio.to_thread(_load_tracked_stocks, uid)
    quotes = await repository.get_quotes(stock.symbol for stock in stocks)
    return {
        "type": "quotes",
        "generated_at": utc_isoformat(utc_now()),
        "quotes": [_quote_payload(stock, quotes.get(stock.symbol)) for stock in stocks],
    }


@router.websocket("/ws")
async def realtime_quotes(websocket: WebSocket) -> None:
    """Push the current Redis quote snapshot every five seconds."""
    session = websocket.cookies.get(COOKIE_NAME)
    uid = parse_session_uid(session or "")
    if uid is None:
        await websocket.accept()
        await websocket.close(code=4401, reason="Login required")
        return
    if not await asyncio.to_thread(_user_exists, uid):
        await websocket.accept()
        await websocket.close(code=4401, reason="Login required")
        return

    repository = RealtimeStateRepository.from_url(get_database_config().redis_url)
    await websocket.accept()
    try:
        while True:
            try:
                await websocket.send_json(await _build_snapshot(uid, repository))
            except WebSocketDisconnect:
                raise
            except Exception as exc:
                logger.warning("实时行情推送失败: uid=%s error=%s", uid, exc, exc_info=True)
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "实时行情暂时不可用",
                        "generated_at": utc_isoformat(utc_now()),
                    }
                )
            await asyncio.sleep(PUSH_INTERVAL_SECONDS)
    except (WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
        pass
    finally:
        await repository.close()
