"""Market-local session boundaries shared by ingestion and cache-only display."""

from datetime import timedelta
from functools import lru_cache

from finance_analysis.market_stream.config import market_spec, market_trading_date
from finance_analysis.market_review.trading_calendar import MARKET_EXCHANGE, xcals


def get_calendar(market):
    return xcals.get_calendar(MARKET_EXCHANGE[market.lower()])


@lru_cache(maxsize=512)
def session_bounds(market, day):
    cal = get_calendar(market.lower())
    if not cal.is_session(day.isoformat()):
        return None
    session = cal.date_to_session(day.isoformat(), direction="none")
    return cal.session_open(session).to_pydatetime(), cal.session_close(session).to_pydatetime()


def in_session(market, now):
    bounds = session_bounds(market, market_trading_date(now, market))
    if bounds is None or not bounds[0] <= now < bounds[1]:
        return False
    local = now.astimezone(market_spec(market).timezone).time().replace(tzinfo=None)
    return any(start <= local < end for start, end in market_spec(market).regular_sessions)


def cache_ttl(market, day, now):
    """Retain the latest session through weekends/holidays, until the next session ends."""
    cal = get_calendar(market.lower())
    following = cal.date_to_session((day + timedelta(days=1)).isoformat(), direction="next")
    expires = cal.session_close(following).to_pydatetime() + timedelta(hours=2)
    return max(60, int((expires - now).total_seconds()))


def display_day(market, now):
    local_day = market_trading_date(now, market)
    bounds = session_bounds(market, local_day)
    if bounds is not None and now >= bounds[0]:
        return local_day
    cal = get_calendar(market.lower())
    previous = cal.date_to_session((local_day - timedelta(days=1)).isoformat(), direction="previous")
    return previous.date()
