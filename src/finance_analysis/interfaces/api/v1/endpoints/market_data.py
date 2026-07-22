"""Authenticated WebSocket stream for user-scoped realtime market quotes."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, cast

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from finance_analysis.core.time import utc_isoformat, utc_now
from finance_analysis.database.config import get_database_config
from finance_analysis.database.repositories.stock_list import StockListRepo
from finance_analysis.database.repositories.user import UserRepository
from finance_analysis.database.repositories.watch_list import WatchListRepo
from finance_analysis.integrations.market_data.providers.longbridge.market import _to_longbridge_symbol
from finance_analysis.integrations.market_data.realtime_state.models import QuoteState, TrendState
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.market_review.trading_calendar import get_completed_trading_days, is_market_open
from finance_analysis.market_stream.config import (
    is_regular_session_minute,
    is_regular_trade_session,
    market_trading_date,
)
from finance_analysis.market_stream.patterns.config import PatternConfig
from finance_analysis.market_stream.patterns.models import PatternSignal, PatternState
from finance_analysis.stocks.markets import MarketType
from finance_analysis.users.auth import COOKIE_NAME, parse_session_uid


PATTERN_CONFIG = PatternConfig()

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
    tracked: dict[str, TrackedStock] = {}
    for item in items:
        code = str(item.code).strip().upper()
        market_type = str(item.market_type).strip().upper()
        try:
            symbol = _to_longbridge_symbol(code)
        except Exception as exc:
            logger.warning("无法转换实时行情代码: code=%s market=%s error=%s", code, market_type, exc)
            continue
        if symbol:
            tracked[symbol.upper()] = TrackedStock(code=code, market_type=market_type, symbol=symbol)
    return list(tracked.values())


def _user_exists(uid: int) -> bool:
    return UserRepository().get_by_uid(uid) is not None


def _number(value: Decimal | int | None) -> float | int | None:
    if value is None:
        return None
    return int(value) if isinstance(value, int) else float(value)


def _trend_payload(trend: TrendState) -> dict[str, Any]:
    return {
        "timeframe": trend.timeframe,
        "target_period": trend.target_period,
        "effective_period": trend.effective_period,
        "minimum_period": trend.minimum_period,
        "state": trend.state,
        "streak": trend.streak,
        "ma_value": _number(trend.ma_value),
        "close": _number(trend.close),
        "distance_pct": _number(trend.distance_pct),
        "bar_time": utc_isoformat(trend.bar_time),
        "trading_date": trend.trading_date.isoformat() if trend.trading_date else None,
        "trade_session": trend.trade_session,
        "confirmed": trend.confirmed,
    }


def _pattern_signal_payload(signal: PatternSignal) -> dict[str, Any]:
    return {
        "timeframe": signal.timeframe,
        "pattern_type": signal.pattern_type,
        "pattern_name": signal.pattern_name,
        "direction": signal.direction,
        "stage": signal.stage,
        "quality_score": signal.quality_score,
        "occurred_at": utc_isoformat(signal.occurred_at),
        "confirmed_at": utc_isoformat(signal.confirmed_at),
        "trading_date": signal.trading_date.isoformat() if signal.trading_date else None,
        "trade_session": signal.trade_session,
        "bars_ago": signal.bars_ago,
        "session_minutes_ago": signal.session_minutes_ago,
        "reference_level": _number(signal.reference_level),
        "invalidation_price": _number(signal.invalidation_price),
        "reasons": list(signal.reasons),
        "confirmed": signal.confirmed,
    }


def _pattern_payload(pattern: PatternState) -> dict[str, Any]:
    return {
        "timeframe": pattern.timeframe,
        "status": pattern.status,
        "trading_date": pattern.trading_date.isoformat() if pattern.trading_date else None,
        "bar_time": utc_isoformat(pattern.bar_time),
        "signal": _pattern_signal_payload(pattern.signal) if pattern.signal else None,
    }


def _display_trading_date(market_type: str, now: datetime) -> date:
    market = market_type.lower()
    local_date = market_trading_date(now, cast(MarketType, market_type))
    if is_market_open(market, local_date):
        return local_date
    return get_completed_trading_days(market, 1, now)[-1]


def _quote_payload(
    stock: TrackedStock,
    quote: QuoteState | None,
    trend: TrendState | None,
    pattern: PatternState | None,
    *,
    now: datetime,
) -> dict[str, Any]:
    try:
        display_date = _display_trading_date(stock.market_type, now)
        trend_is_current = trend is not None and trend.trading_date == display_date
        if trend_is_current and trend is not None and trend.bar_time is not None:
            trend_is_current = (
                market_trading_date(trend.bar_time, cast(MarketType, stock.market_type)) == display_date
                and is_regular_session_minute(trend.bar_time, cast(MarketType, stock.market_type))
                and is_regular_trade_session(trend.trade_session)
            )
        if trend_is_current and trend is not None and trend.state != "insufficient":
            trend_is_current = trend.confirmed and trend.bar_time is not None
    except Exception as exc:
        logger.warning("趋势交易日校验失败: symbol=%s error=%s", stock.symbol, exc)
        display_date = None
        trend_is_current = False
    if not trend_is_current:
        trend = TrendState(symbol=stock.symbol, trading_date=display_date)
    original_pattern = pattern
    try:
        pattern_is_current = pattern is not None and pattern.trading_date == display_date
        if pattern_is_current and pattern is not None and pattern.bar_time is not None:
            pattern_is_current = (
                market_trading_date(pattern.bar_time, cast(MarketType, stock.market_type)) == display_date
                and is_regular_session_minute(pattern.bar_time, cast(MarketType, stock.market_type))
            )
        if pattern_is_current and pattern is not None and pattern.signal is not None:
            effective_at = pattern.signal.confirmed_at or pattern.signal.occurred_at
            pattern_is_current = (
                pattern.signal.trading_date == display_date
                and is_regular_session_minute(effective_at, cast(MarketType, stock.market_type))
                and is_regular_trade_session(pattern.signal.trade_session)
                and pattern.signal.bars_ago <= PATTERN_CONFIG.maximum_age_bars
            )
    except Exception as exc:
        logger.warning("形态交易日校验失败: symbol=%s error=%s", stock.symbol, exc)
        pattern_is_current = False
    if not pattern_is_current:
        pattern = PatternState(
            symbol=stock.symbol,
            status="insufficient" if original_pattern is None else "none",
            trading_date=display_date,
        )
    base: dict[str, Any] = {
        **asdict(stock),
        "available": quote is not None,
        "trend_1m": _trend_payload(trend),
        "pattern_1m": _pattern_payload(pattern),
    }
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
    symbols = [stock.symbol for stock in stocks]
    quotes_result, trends_result, patterns_result = await asyncio.gather(
        repository.get_quotes(symbols),
        repository.get_trend_states(symbols),
        repository.get_pattern_states(symbols),
        return_exceptions=True,
    )
    if isinstance(quotes_result, BaseException):
        raise quotes_result
    quotes = quotes_result
    if isinstance(trends_result, BaseException):
        logger.warning("批量读取实时趋势失败: %s", trends_result)
        trends: dict[str, TrendState] = {}
    else:
        trends = trends_result
    if isinstance(patterns_result, BaseException):
        logger.warning("批量读取实时形态失败: %s", patterns_result)
        patterns: dict[str, PatternState] = {}
    else:
        patterns = patterns_result
    now = utc_now()
    return {
        "type": "quotes",
        "generated_at": utc_isoformat(now),
        "quotes": [
            _quote_payload(
                stock,
                quotes.get(stock.symbol),
                trends.get(stock.symbol),
                patterns.get(stock.symbol),
                now=now,
            )
            for stock in stocks
        ],
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
