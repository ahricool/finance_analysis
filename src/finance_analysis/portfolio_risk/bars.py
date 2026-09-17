# -*- coding: utf-8 -*-
"""Regular-session 5m bar construction, quality filters, and timestamp semantics."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable, Literal
from zoneinfo import ZoneInfo

from finance_analysis.integrations.market_data.models import MarketBar  # pragma: allowlist secret
from finance_analysis.market_review.trading_calendar import MARKET_EXCHANGE, MARKET_TIMEZONE, is_market_open  # pragma: allowlist secret
from finance_analysis.market_stream.config import MARKET_SPECS  # pragma: allowlist secret

TimestampKind = Literal["start", "end"]
PROVIDER_TIMESTAMP_KIND: dict[str, TimestampKind] = {
    "sina_minute": "end",
    "yfinance": "start",
}
INTERVAL = timedelta(minutes=5)


def adjacent(left: NormalizedBar, right: NormalizedBar) -> bool:
    """True when `right` is the next regular-session 5m slot after `left`."""

    if left.symbol != right.symbol or left.session_id != right.session_id:
        return False
    return abs((right.bar_start - left.bar_end).total_seconds()) < 1


@dataclass(frozen=True, slots=True)
class NormalizedBar:
    symbol: str
    market: str
    trade_date: date
    bar_start: datetime
    bar_end: datetime
    session_id: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    amount: Decimal | None
    amount_quality: str
    volume_quality: str
    provider: str
    closed: bool
    slot_key: str


def market_zone(market: str) -> ZoneInfo:
    return ZoneInfo(MARKET_TIMEZONE[market.lower()])


def _sessions(market: str, trade_date: date) -> list[tuple[datetime, datetime, str]]:
    spec = MARKET_SPECS[market.upper()]
    tz = spec.timezone
    sessions = []
    labels = ("AM", "PM") if len(spec.regular_sessions) > 1 else ("RTH",)
    for index, (start, end) in enumerate(spec.regular_sessions):
        sessions.append(
            (
                datetime.combine(trade_date, start, tzinfo=tz),
                datetime.combine(trade_date, end, tzinfo=tz),
                f"{trade_date.isoformat()}|{labels[index]}",
            )
        )
    if market.upper() == "US":
        close = _exchange_close("us", trade_date)
        if close is not None:
            start, _end, label = sessions[0]
            sessions = [(start, min(close, sessions[0][1]), label)]
    return sessions


def _exchange_close(market: str, trade_date: date) -> datetime | None:
    try:
        import exchange_calendars as xcals

        cal = xcals.get_calendar(MARKET_EXCHANGE[market])
        session = datetime(trade_date.year, trade_date.month, trade_date.day)
        if not cal.is_session(session):
            return None
        close = cal.session_close(cal.date_to_session(session, direction="none"))
        tz = market_zone(market)
        if hasattr(close, "tz_convert"):
            return close.tz_convert(str(tz)).to_pydatetime()
        if close.tzinfo is not None:
            return close.astimezone(tz)
        return close.replace(tzinfo=tz)
    except Exception:
        return None


def regular_5m_slots(market: str, trade_date: date) -> list[tuple[datetime, datetime, str]]:
    slots = []
    for start, end, session_id in _sessions(market, trade_date):
        cursor = start
        while cursor + INTERVAL <= end + timedelta(seconds=1):
            bar_end = cursor + INTERVAL
            if bar_end > end:
                break
            slots.append((cursor, bar_end, session_id))
            cursor = bar_end
    return slots


def opening_observation_ends(market: str, trade_date: date) -> set[datetime]:
    slots = regular_5m_slots(market, trade_date)
    return {slot[1] for slot in slots[:2]}


def is_complete_session_day(market: str, trade_date: date, bars: Iterable[NormalizedBar]) -> bool:
    if not is_market_open(market.lower(), trade_date):
        return False
    expected = {slot[1] for slot in regular_5m_slots(market, trade_date)}
    if not expected:
        return False
    present = {bar.bar_end for bar in bars if bar.trade_date == trade_date and bar.closed}
    return expected <= present


def _ohlc_valid(open_: Decimal, high: Decimal, low: Decimal, close: Decimal) -> bool:
    if min(open_, high, low, close) <= 0:
        return False
    return low <= min(open_, close) and high >= max(open_, close) and high >= low


def normalize_market_bar(
    bar: MarketBar,
    *,
    now: datetime,
    kind: TimestampKind | None = None,
) -> NormalizedBar | None:
    resolved_kind = kind or PROVIDER_TIMESTAMP_KIND.get(bar.provider)
    raw = bar.bar_time
    if bar.bar_start and bar.bar_end:
        bar_start, bar_end = bar.bar_start, bar.bar_end
    elif raw is None or resolved_kind is None:
        return None
    elif resolved_kind == "end":
        bar_end = raw
        bar_start = bar.bar_start or (bar_end - INTERVAL)
    else:
        bar_start = raw
        bar_end = bar.bar_end or (bar_start + INTERVAL)
    if bar_start.tzinfo is None or bar_end.tzinfo is None:
        return None
    market = bar.market.value if hasattr(bar.market, "value") else str(bar.market)
    local_end = bar_end.astimezone(market_zone(market))
    slot = next(
        (
            item
            for item in regular_5m_slots(market, local_end.date())
            if item[1] == bar_end or abs((item[1] - bar_end).total_seconds()) < 1
        ),
        None,
    )
    if slot is None:
        return None
    bar_start, bar_end, session_id = slot
    open_ = Decimal(str(bar.open))
    high = Decimal(str(bar.high))
    low = Decimal(str(bar.low))
    close = Decimal(str(bar.close))
    if not _ohlc_valid(open_, high, low, close):
        return None
    volume = int(bar.volume)
    volume_quality = "ok"
    if volume < 0:
        return None
    if volume == 0:
        volume_quality = "zero"
    amount = None if bar.amount is None else Decimal(str(bar.amount))
    if amount is not None and amount < 0:
        amount = None
    amount_quality = "exact" if amount is not None and not bar.amount_estimated else "missing"
    closed = now >= bar_end
    return NormalizedBar(
        symbol=bar.symbol,
        market=market,
        trade_date=local_end.date(),
        bar_start=bar_start,
        bar_end=bar_end,
        session_id=session_id,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        amount=amount,
        amount_quality=amount_quality,
        volume_quality=volume_quality,
        provider=bar.provider,
        closed=closed,
        slot_key=bar_end.astimezone(market_zone(market)).strftime("%H:%M"),
    )


def dedupe_closed(bars: Iterable[NormalizedBar]) -> list[NormalizedBar]:
    unique: dict[datetime, NormalizedBar] = {}
    for bar in bars:
        if not bar.closed:
            continue
        unique[bar.bar_end] = bar
    ordered = [unique[key] for key in sorted(unique)]
    cleaned: list[NormalizedBar] = []
    previous = None
    for bar in ordered:
        if previous is not None and bar.bar_end <= previous.bar_end:
            continue
        cleaned.append(bar)
        previous = bar
    return cleaned


def latest_expected_closed(market: str, now: datetime) -> datetime | None:
    local = now.astimezone(market_zone(market))
    slots = regular_5m_slots(market, local.date())
    closed = [end for _start, end, _session in slots if now >= end]
    return closed[-1] if closed else None


def in_evaluation_window(market: str, now: datetime, *, close_buffer: timedelta = timedelta(minutes=5)) -> bool:
    local = now.astimezone(market_zone(market))
    for start, end, _session in _sessions(market, local.date()):
        if start <= local < end + close_buffer:
            return True
    return False


def apply_volume_quality(bars: Iterable[NormalizedBar]) -> list[NormalizedBar]:
    """Keep a single true zero-volume bar distinct from a consecutive zero run."""

    grouped: dict[str, list[NormalizedBar]] = {}
    for bar in bars:
        grouped.setdefault(bar.session_id, []).append(bar)
    updated: list[NormalizedBar] = []
    for session_bars in grouped.values():
        streak = 0
        for bar in sorted(session_bars, key=lambda item: item.bar_end):
            if bar.volume == 0:
                streak += 1
                quality = "unreliable" if streak >= 3 else "zero"
            else:
                streak = 0
                quality = "ok"
            if quality != bar.volume_quality:
                bar = replace(bar, volume_quality=quality)
            updated.append(bar)
    return sorted(updated, key=lambda item: item.bar_end)
