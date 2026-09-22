"""Explicit closed CN sessions, with bounded upstream history."""

from datetime import timedelta
from finance_analysis.market_review import trading_calendar as calendar


def sessions_through(day, count):
    if not calendar._XCALS_AVAILABLE:
        raise ValueError("A股交易日历不可用")
    return calendar.get_trading_days_between("cn", day - timedelta(days=count * 3 + 30), day)[-count:]


def expected_date():
    today = calendar.get_market_now("cn").date()
    return next(
        d for d in reversed(sessions_through(today, 2)) if calendar.is_market_session_closed("cn", check_date=d)
    )


def validate_day(day):
    today = calendar.get_market_now("cn").date()
    if day < today - timedelta(days=364) or day > today:
        raise ValueError("扶摇龙虎榜仅支持一年内日期")
    if day not in sessions_through(day, 1) or not calendar.is_market_session_closed("cn", check_date=day):
        raise ValueError("只支持已收盘的A股交易日")
