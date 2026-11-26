"""Market-local session boundaries shared by ingestion and cache-only display."""

from datetime import time, timedelta
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


def us_minute_session(stamp, label=None):
    """Prefer the provider session; infer historical labels with the exchange calendar."""
    normalized = (label or "").lower()
    if "pre" in normalized:
        return "pre"
    if "post" in normalized:
        return "post"
    if "night" in normalized:
        return "overnight"
    bounds = session_bounds("US", market_trading_date(stamp, "US"))
    local = stamp.astimezone(market_spec("US").timezone).time()
    if bounds and bounds[0] <= stamp < bounds[1]:
        return "regular"
    if local < time(4) or local >= time(20):
        return "overnight"
    if local < time(9, 30):
        return "pre"
    return "post"


def cache_ttl(market, day, now):
    """Retain the latest session through weekends/holidays, until the next session ends."""
    cal = get_calendar(market.lower())
    following = cal.date_to_session((day + timedelta(days=1)).isoformat(), direction="next")
    expires = cal.session_close(following).to_pydatetime() + timedelta(hours=2)
    return max(60, int((expires - now).total_seconds()))


@lru_cache(maxsize=512)
def previous_session_date(market, day):
    cal = get_calendar(market)
    return cal.date_to_session((day - timedelta(days=1)).isoformat(), direction="previous").date()


def display_day(market, now):
    local_day = market_trading_date(now, market)
    bounds = session_bounds(market, local_day)
    if bounds is not None and now >= bounds[0]:
        return local_day
    return previous_session_date(market, local_day)


def quote_display_date_matches(market, now, day):
    """US premarket/overnight quotes may already belong to the current civil date."""
    return day == display_day(market, now) or (market == "US" and day == market_trading_date(now, market))
