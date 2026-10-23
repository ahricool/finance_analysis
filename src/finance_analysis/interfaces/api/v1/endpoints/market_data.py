"""Authenticated daily bars and user-scoped realtime market quotes."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal, cast

from anyio import CancelScope
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from finance_analysis.core.time import utc_isoformat, utc_now
from finance_analysis.database.repositories.user import UserRepository
from finance_analysis.database.repositories.watch_list import WatchListRepo
from finance_analysis.integrations.market_data.forward_returns import forward_returns
from finance_analysis.integrations.market_data.normalizer import canonical_symbol, infer_market
from finance_analysis.integrations.market_data.providers.longbridge.market import _to_longbridge_symbol
from finance_analysis.integrations.market_data.realtime_state.models import QuoteState, TrendState
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.integrations.market_data.service import MarketDataService
from finance_analysis.interfaces.api.v1.schemas.market_data import (
    DailyBarItem,
    DailyBarsResponse,
    ForwardReturnsRequest,
    ForwardReturnsResponse,
    IntradayBarsResponse,
)
from finance_analysis.interfaces.api.deps import get_effective_uid, require_current_user
from finance_analysis.portfolio.valuation import portfolio_summary
from finance_analysis.market_stream.config import (
    is_regular_session_minute,
    is_regular_trade_session,
    latest_completed_bar_time,
    MarketStreamConfig,
    market_spec,
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
SSE_HEARTBEAT_SECONDS = 10


@router.get("/intraday/{symbol}", response_model=IntradayBarsResponse, dependencies=[Depends(require_current_user)])
async def intraday_bars(symbol: str, request: Request, since: datetime | None = None, response: Response = None):
    """User-owned intraday view; cache misses never launch an external request."""
    from finance_analysis.portfolio.service import PortfolioService

    if response is not None:
        response.headers["Cache-Control"] = "private, no-store"

    try:
        code = canonical_symbol(symbol)
        market = infer_market(code).value
        if market not in {"CN", "US"} or (since is not None and since.tzinfo is None):
            raise ValueError("invalid market or timestamp")
    except ValueError as exc:
        raise HTTPException(422, "证券或时间格式无效") from exc
    uid = get_effective_uid(request)
    tracked = await asyncio.to_thread(_load_tracked_stocks, uid, market)
    if code not in {stock.symbol for stock in tracked}:
        held = await asyncio.to_thread(PortfolioService().list_positions, uid, market=market)
        if code not in {row["symbol"] for row in held}:
            raise HTTPException(404, "证券不在本人的自选股或持仓中")
    repository = RealtimeStateRepository.from_url(MarketStreamConfig.from_env().redis_url)
    try:
        now = utc_now()
        day = _display_trading_date(market, now)
        async def read_candles():
            if market == "CN":
                return await repository.get_intraday_snapshot(code)
            return await asyncio.gather(repository.get_recent_bars(code, 420), repository.get_current_candle(code))

        (bars, current), snapshot, events = await asyncio.gather(
            read_candles(),
            _build_snapshot(uid, repository, stocks=[TrackedStock(code, market, code)]),
            repository.get_pattern_events(code, day),
        )
        reset = since is None or market_trading_date(since, market) != day
        by_time = {bar.bar_time: bar for bar in bars}
        if current is not None and (current.bar_time not in by_time or not by_time[current.bar_time].confirmed):
            by_time[current.bar_time] = current
        items = [
            {
                "timestamp": int(bar.bar_time.timestamp() * 1000),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": bar.volume,
                "turnover": float(bar.turnover) if bar.turnover is not None else None,
                "confirmed": bar.confirmed,
                "sampled": bar.sampled,
                "sample_count": bar.sample_count,
                "partial": bar.partial,
                "source": bar.source,
            }
            for bar in sorted(by_time.values(), key=lambda b: b.bar_time)
            if market_trading_date(bar.bar_time, market) == day
            and bar.is_valid()
            and is_regular_session_minute(bar.bar_time, market)
            and bar.bar_time <= now
            and (market == "CN" or reset or bar.bar_time >= since)
        ]
        return {
            "symbol": code,
            "market": market,
            "trading_date": day,
            "generated_at": now,
            "reset": reset,
            "full_snapshot": market == "CN",
            "items": items,
            "quote": snapshot["quotes"][0],
            "events": events,
        }
    finally:
        with CancelScope(shield=True):
            await repository.close()


@router.post("/forward-returns", response_model=ForwardReturnsResponse)
def research_forward_returns(body: ForwardReturnsRequest):
    """Batch read-only evaluation; POST carries the large research universe."""
    try:
        symbols = list(dict.fromkeys(canonical_symbol(code) for code in body.symbols))
        if any(infer_market(code).value != body.market for code in symbols):
            raise ValueError("证券代码与市场不匹配")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        return forward_returns(MarketDataService(), symbols, body.market, body.trade_date)
    except Exception as exc:
        logger.warning("Forward returns unavailable", exc_info=True)
        raise HTTPException(status_code=503, detail="未来收益率暂时不可用，请稍后重试") from exc


@router.get("/daily-bars/{symbol}", response_model=DailyBarsResponse)
def daily_bars(symbol: str, start_date: date | None = None, end_date: date | None = None) -> DailyBarsResponse:
    """Serve a bounded daily window without persisting provider results."""
    try:
        code = canonical_symbol(symbol)
        market = infer_market(code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    now = utc_now()
    end = end_date or (now.date() if market.value == "HK" else market_trading_date(now, market.value))
    start = start_date or end - timedelta(days=365)
    if start > end:
        raise HTTPException(status_code=422, detail="start_date must not be after end_date")
    history_fallback = False
    try:
        service = MarketDataService()
        unavailable = False
        try:
            result = service.get_daily_bars([code], start, end, adjustment="forward", source_policy="db_latest")
            bars = result.data.get(code, [])
            source = result.providers_used.get(code)
            unavailable = code in result.failed_symbols or code in result.request_errors
        except Exception:
            logger.warning("Latest daily bars unavailable: %s", code, exc_info=True)
            bars, source, unavailable = [], None, True
        if not bars:
            try:
                stored = service.get_daily_bars([code], start, end, adjustment="forward", source_policy="db_only")
                bars = stored.data.get(code, [])
                if bars:
                    source = "database"
                    history_fallback = True
            except Exception:
                logger.warning("Stored daily bars unavailable: %s", code, exc_info=True)
                unavailable = True
    except Exception as exc:
        logger.warning("Daily bars unavailable: %s", code, exc_info=True)
        raise HTTPException(status_code=503, detail="日 K 数据暂时不可用，请稍后重试") from exc
    if not bars and unavailable:
        raise HTTPException(status_code=503, detail="日 K 数据暂时不可用，请稍后重试")
    by_date = {bar.trade_date: bar for bar in bars}
    try:
        today_bar = service.get_intraday_daily_bar(code, start, end, now=now)
        if today_bar is not None:
            by_date[today_bar.trade_date] = today_bar
    except Exception:
        logger.warning("Intraday daily overlay unavailable: %s", code, exc_info=True)
    return DailyBarsResponse(
        symbol=code,
        market=market.value,
        source=source,
        history_fallback=history_fallback,
        items=[
            DailyBarItem(
                trade_date=bar.trade_date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                amount=bar.amount,
            )
            for bar in sorted(by_date.values(), key=lambda bar: bar.trade_date)
            if start <= bar.trade_date <= end
        ],
    )


@dataclass(frozen=True, slots=True)
class TrackedStock:
    code: str
    market_type: str
    symbol: str


def _load_tracked_stocks(
    uid: int,
    market: str | None = None,
    tag_id: int | None = None,
    ungrouped: bool = False,
) -> list[TrackedStock]:
    tracked: dict[str, TrackedStock] = {}
    filters = {"market_type": market, "tag_id": tag_id, "ungrouped": ungrouped} if market or tag_id or ungrouped else {}
    for item in WatchListRepo().list_all(uid=uid, **filters):
        code = str(item.code).strip().upper()
        market_type = str(item.market_type).strip().upper()
        try:
            symbol = canonical_symbol(code) if market_type == "CN" else _to_longbridge_symbol(code)
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
        "preview_status": pattern.preview_status,
        "preview_signal": _pattern_signal_payload(pattern.preview_signal) if pattern.preview_signal else None,
        "preview_bar_time": utc_isoformat(pattern.preview_bar_time),
        "preview_price": _number(pattern.preview_price),
        "preview_updated_at": utc_isoformat(pattern.preview_updated_at),
    }


def _display_trading_date(market_type: str, now: datetime) -> date:
    from finance_analysis.market_stream.session import display_day

    return display_day(market_type, now)


def _preview_bar_is_current(
    preview_bar_time: datetime,
    *,
    now: datetime,
    market_type: MarketType,
    display_date: date | None,
) -> bool:
    """Return whether a preview bar is the market's still-forming regular-session minute."""
    if display_date is None or market_trading_date(now, market_type) != display_date:
        return False
    if not is_regular_session_minute(now, market_type):
        return False
    if market_trading_date(preview_bar_time, market_type) != display_date:
        return False
    if not is_regular_session_minute(preview_bar_time, market_type):
        return False

    spec = market_spec(market_type)
    current_minute = now.astimezone(spec.timezone).replace(second=0, microsecond=0)
    preview_minute = preview_bar_time.astimezone(spec.timezone).replace(second=0, microsecond=0)
    if preview_minute != current_minute:
        return False

    latest_completed = latest_completed_bar_time(now, market_type)
    return latest_completed is None or preview_bar_time > latest_completed


def _session_window(market, now):
    from finance_analysis.market_stream.session import session_bounds

    return session_bounds(market, _display_trading_date(market, now)) or (None, None)


def _market_is_open(market, now):
    from finance_analysis.market_stream.session import in_session

    return in_session(market, now)


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
        quote_is_current = (
            quote is not None
            and quote.trading_date == display_date
            and quote.last_price is not None
            and quote.last_price > 0
            and quote.event_time is not None
            and quote.received_at is not None
            and quote.timestamp_kind != "received"
            and quote.event_time <= now + timedelta(seconds=5)
            and quote.received_at <= now + timedelta(seconds=5)
        )
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
        logger.warning("行情交易日校验失败: symbol=%s error=%s", stock.symbol, exc)
        display_date = None
        quote_is_current = False
        trend_is_current = False
    if not trend_is_current:
        trend = TrendState(symbol=stock.symbol, trading_date=display_date)
    preview_is_current = False
    try:
        pattern_is_current = pattern is not None and pattern.trading_date == display_date
        if pattern_is_current and pattern is not None and pattern.bar_time is not None:
            pattern_is_current = market_trading_date(
                pattern.bar_time, cast(MarketType, stock.market_type)
            ) == display_date and is_regular_session_minute(pattern.bar_time, cast(MarketType, stock.market_type))
        if pattern_is_current and pattern is not None and pattern.signal is not None:
            effective_at = pattern.signal.confirmed_at or pattern.signal.occurred_at
            pattern_is_current = (
                pattern.signal.trading_date == display_date
                and is_regular_session_minute(effective_at, cast(MarketType, stock.market_type))
                and is_regular_trade_session(pattern.signal.trade_session)
                and pattern.signal.bars_ago <= PATTERN_CONFIG.maximum_age_bars
            )
        preview_is_current = pattern is not None and pattern.preview_bar_time is not None
        if preview_is_current and pattern is not None and pattern.preview_bar_time is not None:
            preview_is_current = _preview_bar_is_current(
                pattern.preview_bar_time,
                now=now,
                market_type=cast(MarketType, stock.market_type),
                display_date=display_date,
            )
        if preview_is_current and pattern is not None and pattern.preview_signal is not None:
            preview_is_current = (
                pattern.preview_signal.trading_date == display_date
                and is_regular_trade_session(pattern.preview_signal.trade_session)
                and not pattern.preview_signal.confirmed
                and pattern.preview_signal.stage != "confirmed"
            )
    except Exception as exc:
        logger.warning("形态交易日校验失败: symbol=%s error=%s", stock.symbol, exc)
        pattern_is_current = False
        preview_is_current = False
    if pattern is None:
        pattern = PatternState(
            symbol=stock.symbol,
            status="insufficient",
            trading_date=display_date,
        )
    else:
        pattern = PatternState(
            symbol=pattern.symbol,
            status=pattern.status if pattern_is_current else "none",
            signal=pattern.signal if pattern_is_current else None,
            trading_date=pattern.trading_date if pattern_is_current else display_date,
            bar_time=pattern.bar_time if pattern_is_current else None,
            preview_status=pattern.preview_status if preview_is_current else "none",
            preview_signal=pattern.preview_signal if preview_is_current else None,
            preview_bar_time=pattern.preview_bar_time if preview_is_current else None,
            preview_price=pattern.preview_price if preview_is_current else None,
            preview_updated_at=pattern.preview_updated_at if preview_is_current else None,
        )
    if not quote_is_current:
        if quote is not None:
            logger.debug(
                "忽略非展示交易日行情: symbol=%s quote_date=%s display_date=%s",
                stock.symbol,
                quote.trading_date,
                display_date,
            )
        quote = None
    base: dict[str, Any] = {
        **asdict(stock),
        "available": quote is not None,
        "trading_date": quote.trading_date.isoformat() if quote is not None else None,
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
        "timestamp_kind": quote.timestamp_kind,
        "source": quote.source,
        "session_open": utc_isoformat(_session_window(stock.market_type, now)[0]),
        "session_close": utc_isoformat(_session_window(stock.market_type, now)[1]),
        "market_open": _market_is_open(stock.market_type, now),
    }


async def _build_snapshot(
    uid: int,
    repository: RealtimeStateRepository,
    market: str | None = None,
    tag_id: int | None = None,
    ungrouped: bool = False,
    *,
    stocks=None,
) -> dict[str, Any]:
    filters = (market, tag_id, ungrouped) if market or tag_id or ungrouped else ()
    if stocks is None:
        stocks = await asyncio.to_thread(_load_tracked_stocks, uid, *filters)
    symbols = [stock.symbol for stock in stocks]
    quotes_result, trends_result, patterns_result = await asyncio.gather(
        repository.get_quotes(symbols),
        repository.get_trend_states(symbols),
        repository.get_pattern_states(symbols),
        return_exceptions=True,
    )
    quotes = {} if isinstance(quotes_result, BaseException) else quotes_result
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
    payloads = []
    for stock in stocks:
        quote = quotes.get(stock.symbol)
        payload = _quote_payload(stock, quote, trends.get(stock.symbol), patterns.get(stock.symbol), now=now)
        payload.update(
            source=quote.source if quote is not None else "streaming",
            quote_status=_display_quote_status(quote, now) if payload["available"] else "unavailable",
        )
        payloads.append(payload)
    return {
        "type": "quotes",
        "generated_at": utc_isoformat(now),
        "quotes": payloads,
    }


def _decimal(value):
    return Decimal(str(value)) if value is not None else None


def _display_quote_status(quote, now):
    if quote is None or quote.event_time is None:
        return "unavailable"
    return "delayed" if now - quote.event_time > timedelta(seconds=90) else "current"


async def _live_snapshot(uid, repository, scope, market, tag_id=None, ungrouped=False):
    if scope == "holdings":
        portfolio = await asyncio.to_thread(portfolio_summary, uid, market or "CN", initialize_accounts=False)
        stocks = [TrackedStock(row["symbol"], row["market"], row["symbol"]) for row in portfolio["positions"]]
        snapshot = await _build_snapshot(uid, repository, stocks=stocks)
        return jsonable_encoder({**snapshot, "generated_at": portfolio["generated_at"], "portfolio": portfolio})
    if market or tag_id or ungrouped:
        return await _build_snapshot(uid, repository, market, tag_id, ungrouped)
    return await _build_snapshot(uid, repository)


@router.get("/events", dependencies=[Depends(require_current_user)])
async def realtime_events(
    request: Request,
    scope: Literal["watch-list", "holdings"] = "watch-list",
    market: Literal["CN", "US", "HK"] | None = None,
    tag_id: Annotated[int | None, Query(ge=1)] = None,
    ungrouped: bool = False,
):
    if tag_id is not None and ungrouped:
        raise HTTPException(status_code=422, detail="不能同时筛选标签与未分组")
    if scope == "holdings" and market == "HK":
        raise HTTPException(status_code=422, detail="持仓行情仅支持美股与 A 股")
    uid = get_effective_uid(request)

    async def events():
        repository = RealtimeStateRepository.from_url(MarketStreamConfig.from_env().redis_url)
        snapshot_task: asyncio.Task[dict[str, Any]] | None = None
        try:
            yield ": connected\n\n"
            while not await request.is_disconnected():
                snapshot_task = asyncio.create_task(_live_snapshot(uid, repository, scope, market, tag_id, ungrouped))
                while True:
                    # Waiting must not cancel or restart a slow provider request.
                    done, _ = await asyncio.wait({snapshot_task}, timeout=SSE_HEARTBEAT_SECONDS)
                    if done:
                        break
                    if await request.is_disconnected():
                        return
                    yield ": heartbeat\n\n"
                try:
                    snapshot = snapshot_task.result()
                except Exception:
                    logger.warning("SSE 行情推送失败 uid=%s", uid, exc_info=True)
                    snapshot = {"type": "error", "message": "实时行情暂时不可用"}
                snapshot_task = None
                yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
                await asyncio.sleep(PUSH_INTERVAL_SECONDS)
        finally:
            # ASGI disconnect cancellation must not interrupt asynchronous resource cleanup.
            with CancelScope(shield=True):
                if snapshot_task is not None:
                    snapshot_task.cancel()
                    # Retrieve completed provider failures without skipping repository cleanup.
                    with suppress(asyncio.CancelledError, Exception):
                        await snapshot_task
                await repository.close()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "private, no-store",
            "X-Accel-Buffering": "no",
        },
    )


@router.websocket("/ws")
async def realtime_quotes(
    websocket: WebSocket,
    scope: Literal["watch-list", "holdings"] = "watch-list",
    market: Literal["CN", "US", "HK"] | None = None,
    tag_id: Annotated[int | None, Query(ge=1)] = None,
    ungrouped: bool = False,
) -> None:
    """Push user-owned market/portfolio snapshots every five seconds."""
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

    if tag_id is not None and ungrouped or scope == "holdings" and market == "HK":
        await websocket.accept()
        await websocket.close(code=1008, reason="Invalid market/group filter")
        return

    repository = RealtimeStateRepository.from_url(MarketStreamConfig.from_env().redis_url)
    await websocket.accept()
    try:
        while True:
            try:
                await websocket.send_json(await _live_snapshot(uid, repository, scope, market, tag_id, ungrouped))
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
