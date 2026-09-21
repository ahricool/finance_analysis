# -*- coding: utf-8 -*-
"""Regular-session evaluation window for Trade Engine Celery tasks."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from finance_analysis.market_review.trading_calendar import MARKET_EXCHANGE, MARKET_TIMEZONE  # pragma: allowlist secret
from finance_analysis.market_stream.config import MARKET_SPECS  # pragma: allowlist secret


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


def in_evaluation_window(market: str, now: datetime, *, close_buffer: timedelta = timedelta(minutes=5)) -> bool:
    local = now.astimezone(market_zone(market))
    for start, end, _session in _sessions(market, local.date()):
        if start <= local < end + close_buffer:
            return True
    return False
