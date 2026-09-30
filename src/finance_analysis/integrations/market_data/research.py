"""Shared exact-session and price validation primitives for research evaluation."""

from math import isfinite
from finance_analysis.market_review import trading_calendar as calendar


def exchange_calendar(market):
    if not calendar._XCALS_AVAILABLE:
        raise ValueError("calendar_unavailable")
    return calendar.xcals.get_calendar(calendar.MARKET_EXCHANGE[market.lower()])


def following_sessions(market, day, count):
    cal = exchange_calendar(market)
    session = cal.date_to_session(day, direction="none")
    result = []
    for _ in range(count):
        session = cal.next_session(session)
        result.append((session.date(), cal.session_close(session).to_pydatetime()))
    return result


def valid_close(row):
    return (
        row is not None
        and row.get("close") is not None
        and isfinite(row["close"])
        and row["close"] > 0
        and row.get("volume") is not None
        and isfinite(row["volume"])
        and row["volume"] > 0
    )


def valid_bar(row):
    if row is None:
        return False
    prices = [row.get(k) for k in ("open", "high", "low", "close")]
    if any(v is None or not isfinite(v) or v <= 0 for v in prices):
        return False
    op, high, low, close = prices
    return low <= min(op, close) <= max(op, close) <= high and valid_close(row)
