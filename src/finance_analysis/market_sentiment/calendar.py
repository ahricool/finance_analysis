"""Fail closed when the exchange calendar cannot establish a completed session."""

from datetime import timedelta
from finance_analysis.market_review import trading_calendar as calendar


def sessions_through(day, count):
    if not calendar._XCALS_AVAILABLE:
        raise ValueError("A股交易日历不可用，不能确认交易日")
    days = calendar.get_trading_days_between("cn", day - timedelta(days=count * 3 + 30), day)
    return days[-count:]


def expected_date():
    now = calendar.get_market_now("cn")
    days = sessions_through(now.date(), 2)
    return next(d for d in reversed(days) if calendar.is_market_session_closed("cn", check_date=d))


def validate_day(day):
    if day not in sessions_through(day, 1) or not calendar.is_market_session_closed("cn", check_date=day):
        raise ValueError("只支持已收盘的 A 股交易日")
