"""Market-local scheduling and default read dates, including NYSE early closes."""

from datetime import date, datetime, timedelta

from finance_analysis.market_review.trading_calendar import (
    get_completed_trading_days,
    get_market_now,
    get_market_session_close,
    is_market_open,
)


def review_window(market: str, now: datetime | None = None):
    local = get_market_now(market.lower(), now)
    if local.weekday() >= 5 or not is_market_open(market.lower(), local.date()):
        return None
    # A shares have a fixed 15:00 close; NYSE uses its real session calendar.
    close = (
        local.replace(hour=15, minute=0, second=0, microsecond=0)
        if market == "CN"
        else get_market_session_close("us", local.date(), local)
    )
    start = close - timedelta(minutes=50)
    if not start <= local < min(start + timedelta(minutes=15), close):
        return None
    return local, start, close


def default_dates(market: str, now: datetime | None = None) -> tuple[date, date]:
    local = get_market_now(market.lower(), now)
    # Midnight guarantees the current session has not yet completed.
    previous = get_completed_trading_days(market.lower(), 1, current_time=local.replace(hour=0, minute=0))
    return local.date(), previous[-1] if previous else local.date() - timedelta(days=1)


def next_review_at(market: str, now: datetime | None = None) -> datetime:
    """Upcoming real trading-session window, never advertise a weekend run."""
    local = get_market_now(market.lower(), now)
    for offset in range(32):
        candidate = local + timedelta(days=offset)
        if candidate.weekday() >= 5 or not is_market_open(market.lower(), candidate.date()):
            continue
        close = (
            candidate.replace(hour=15, minute=0, second=0, microsecond=0)
            if market == "CN"
            else get_market_session_close("us", candidate.date(), candidate)
        )
        target = close - timedelta(minutes=50)
        if local < target + timedelta(minutes=15):
            return target
    raise ValueError("无法确定下一交易日复盘时间")
