"""One transaction and database advisory lock per symbol; no shared Sessions."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
import logging
import math
import threading
import time
from typing import Any

from sqlalchemy import func, or_, select, text

from finance_analysis.database.models.intraday_simulation import (
    IntradaySimulationEvent as Event,
    IntradaySimulationState as State,
    IntradaySimulationTrade as Trade,
)
from finance_analysis.database.session import DatabaseManager
from finance_analysis.intraday_options.config import SYMBOLS, UNIVERSE_KEY, normalize_universe_symbols
from finance_analysis.intraday_options.simulation import dt, statistics, transition

logger = logging.getLogger(__name__)

_UNIVERSE_CACHE_TTL_SECONDS = 300.0
_UNIVERSE_FALLBACK_RETRY_SECONDS = 30.0
_universe_lock = threading.Lock()
_universe_cache: dict[str, Any] = {
    "symbols": None,
    "last_good_db": None,
    "expires_at": 0.0,
}


def reset_universe_cache() -> None:
    """Clear the cached intraday universe resolution (used by tests)."""
    with _universe_lock:
        _universe_cache["symbols"] = None
        _universe_cache["last_good_db"] = None
        _universe_cache["expires_at"] = 0.0


def load_universe_symbols(*, force_refresh: bool = False) -> tuple[str, ...]:
    """Resolve active QQQ (`us_nasdaq100`) universe + SPY/QQQ from PostgreSQL with 5-minute TTL fallback."""
    now = time.monotonic()
    with _universe_lock:
        cached = _universe_cache["symbols"]
        if not force_refresh and cached is not None and now < _universe_cache["expires_at"]:
            return cached

    resolved: tuple[str, ...] = ()
    try:
        from finance_analysis.database.repositories.universe import UniverseResolver

        instruments = UniverseResolver().resolve_universe(UNIVERSE_KEY)
        resolved = normalize_universe_symbols(item.code for item in instruments)
    except Exception:
        logger.warning(
            "读取 PostgreSQL Universe %s 失败，降级使用缓存或内置 QQQ 快照",
            UNIVERSE_KEY,
            exc_info=True,
        )

    now = time.monotonic()
    with _universe_lock:
        if resolved:
            _universe_cache["symbols"] = resolved
            _universe_cache["last_good_db"] = resolved
            _universe_cache["expires_at"] = now + _UNIVERSE_CACHE_TTL_SECONDS
            return resolved
        fallback = _universe_cache["last_good_db"] or SYMBOLS
        _universe_cache["symbols"] = fallback
        _universe_cache["expires_at"] = now + _UNIVERSE_FALLBACK_RETRY_SECONDS
        return fallback


def load_daily_context(
    symbols: Iterable[str],
    trading_date: date,
    *,
    atr_period: int = 14,
    min_atr_samples: int = 7,
    lookback_bars: int = 20,
) -> dict[str, dict[str, Any]]:
    """Batch-load strictly causal (< trading_date) 14-day Daily ATR% and DB prev_close per symbol."""
    from finance_analysis.database.models.stock import Instrument, StockDaily

    codes = tuple(dict.fromkeys(str(sym).strip().upper() for sym in symbols if str(sym or "").strip()))
    if not codes:
        return {}
    limit_per_symbol = max(lookback_bars, atr_period + 1)
    by_code: dict[str, list[tuple[date, float, float, float]]] = {code: [] for code in codes}
    with DatabaseManager.get_instance().session_scope() as session:
        ranked = (
            select(
                Instrument.code.label("code"),
                StockDaily.date.label("trade_date"),
                StockDaily.high.label("high"),
                StockDaily.low.label("low"),
                StockDaily.close.label("close"),
                func.row_number()
                .over(partition_by=StockDaily.instrument_id, order_by=StockDaily.date.desc())
                .label("rn"),
            )
            .join(Instrument, StockDaily.instrument_id == Instrument.id)
            .where(Instrument.code.in_(codes), StockDaily.date < trading_date)
            .subquery()
        )
        rows = session.execute(
            select(ranked.c.code, ranked.c.trade_date, ranked.c.high, ranked.c.low, ranked.c.close)
            .where(ranked.c.rn <= limit_per_symbol)
            .order_by(ranked.c.code.asc(), ranked.c.trade_date.asc())
        ).all()
        for row in rows:
            by_code.setdefault(row.code, []).append((row.trade_date, row.high, row.low, row.close))

    output: dict[str, dict[str, Any]] = {}
    for code in codes:
        bars = by_code.get(code, [])
        tr_samples: list[float] = []
        prev_valid_close: float | None = None
        last_valid_close: float | None = None
        last_valid_date: date | None = None
        for trade_date, raw_hi, raw_lo, raw_close in bars:
            try:
                hi, lo, close = float(raw_hi), float(raw_lo), float(raw_close)
            except (TypeError, ValueError):
                prev_valid_close = None
                continue
            if (
                not (math.isfinite(hi) and math.isfinite(lo) and math.isfinite(close))
                or close <= 0
                or hi < lo
                or lo <= 0
            ):
                prev_valid_close = None
                continue
            if prev_valid_close is not None and prev_valid_close > 0:
                tr_pct = max(hi - lo, abs(hi - prev_valid_close), abs(lo - prev_valid_close)) / prev_valid_close
                if math.isfinite(tr_pct) and tr_pct >= 0:
                    tr_samples.append(tr_pct)
            prev_valid_close = close
            last_valid_close = close
            last_valid_date = trade_date
        recent_tr = tr_samples[-atr_period:]
        daily_atr_pct = sum(recent_tr) / len(recent_tr) if len(recent_tr) >= min_atr_samples else None
        output[code] = {
            "daily_atr_pct": daily_atr_pct,
            "atr_samples": len(recent_tr),
            "prev_close": last_valid_close,
            "as_of": last_valid_date.isoformat() if last_valid_date else None,
        }
    return output


def process_with_events(symbol, result, quote, now):
    committed_events = []
    with DatabaseManager.get_instance().session_scope() as session:
        # Lock also covers absent state rows and serializes independent Streamer instances.
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "intraday-simulation:" + symbol}
        )
        row = session.get(State, symbol)
        previous = row.payload if row else {}
        if previous.get("calculated_at") and dt(previous["calculated_at"]) >= now:
            return previous, []
        state, events = transition(previous, symbol, result, quote, now)
        if row is None:
            session.add(State(symbol=symbol, payload=state))
        else:
            row.payload = state
        for event in events:
            session.add(Event(symbol=symbol, occurred_at=now, payload=event))
            if event["kind"] == "entry":
                trade = event["trade"]
                session.add(
                    Trade(
                        id=trade["id"],
                        symbol=symbol,
                        trading_date=date.fromisoformat(trade["trading_date"]),
                        process_id=trade["process_id"],
                        status="open",
                        payload=trade,
                    )
                )
            elif event["kind"] == "exit":
                trade = session.get(Trade, event["trade_id"])
                trade.status, trade.payload = "closed", event["trade"]
        committed_events = events
    return state, committed_events


def process(symbol, result, quote, now):
    state, _ = process_with_events(symbol, result, quote, now)
    return state


def open_retired_symbols(active_symbols: Iterable[str] | None = None):
    """Continue price-driven exits for positions that predate an observation pool change."""
    active = tuple(active_symbols) if active_symbols is not None else load_universe_symbols()
    with DatabaseManager.get_instance().session_scope() as session:
        return set(session.scalars(select(Trade.symbol).where(Trade.status == "open", Trade.symbol.not_in(active))))


def read(day, after_event_id=None, active_symbols: Iterable[str] | None = None):
    active = set(active_symbols) if active_symbols is not None else set(load_universe_symbols())
    with DatabaseManager.get_instance().session_scope() as session:
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        states = [r.payload for r in session.scalars(select(State)) if r.symbol in active or r.payload.get("position")]
        trades = [
            r.payload for r in session.scalars(select(Trade).where(Trade.trading_date == day, Trade.status == "closed"))
        ]
        # Full durable day snapshot on every reconnect: event IDs deduplicate; no cursor race or loss.
        from finance_analysis.market_stream.session import session_bounds

        bounds = session_bounds("US", day)
        query = select(Event).order_by(Event.id.desc())
        if bounds:
            since = Event.occurred_at >= bounds[0]
            query = query.where(or_(since, Event.id > after_event_id) if after_event_id is not None else since)
        events = [dict(id=r.id, **r.payload) for r in session.scalars(query)]
        return dict(states=states, trades=trades, events=events, statistics=statistics(trades))


def references(day):
    """Optional DB-only context. Missing coverage is explicitly unknown, never neutral."""
    from finance_analysis.database.models.market_calendar import FinanceEvent
    from finance_analysis.database.models.stock import Instrument, StockDaily

    with DatabaseManager.get_instance().session_scope() as session:
        daily = list(
            session.scalars(
                select(StockDaily)
                .join(Instrument)
                .where(Instrument.code == "QQQ.US", StockDaily.date < day)
                .order_by(StockDaily.date.desc())
                .limit(20)
            )
        )
        background = dict(label="未知", as_of=None, reason="QQQ最近已完成日线不足20根")
        if len(daily) == 20:
            mean = sum(r.close for r in daily) / 20
            change = daily[0].close / mean - 1
            background = dict(
                label="偏多" if change > 0.005 else "偏空" if change < -0.005 else "震荡",
                as_of=daily[0].date.isoformat(),
                reason="最近已存完成日线收盘相对20日均线，±0.5%为震荡；仅供参考",
            )
        events = [
            dict(
                title=e.title,
                at=e.event_datetime.isoformat(),
                as_of=e.last_seen_at.isoformat(),
                reason="已有宏观日历事件，临近发布可能增加波动；不参与入场门槛",
            )
            for e in session.scalars(
                select(FinanceEvent).where(
                    FinanceEvent.calendar_type == "macro",
                    FinanceEvent.market == "US",
                    FinanceEvent.event_date == day,
                    FinanceEvent.event_datetime.is_not(None),
                )
            )
        ]
        return dict(
            background=background,
            macro=events,
            macro_status="已存事件，覆盖可能不完整" if events else "暂无可靠时间事件，覆盖未知",
        )
