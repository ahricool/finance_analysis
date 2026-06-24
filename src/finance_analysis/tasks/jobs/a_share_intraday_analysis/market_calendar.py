# -*- coding: utf-8 -*-
"""A-share session helpers and timezone-aware timestamp parsing.

The trading-day / phase logic is shared with the rest of the codebase via
:mod:`finance_analysis.market_review.trading_calendar`; this module re-exports
those helpers and adds intraday minute-bar timestamp parsing.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any, Optional

from finance_analysis.market_review.trading_calendar import (
    ASIA_SHANGHAI,
    get_a_share_market_now,
    get_a_share_market_phase,
    is_a_share_intraday_analysis_time,
    is_a_share_trading_day,
)

__all__ = [
    "ASIA_SHANGHAI",
    "get_a_share_market_now",
    "get_a_share_market_phase",
    "is_a_share_intraday_analysis_time",
    "is_a_share_trading_day",
    "parse_a_share_timestamp",
    "is_lunch_break_time",
]

# Lunch break window (Asia/Shanghai). Bars stamped inside it are spurious.
_LUNCH_START = time(11, 30)
_LUNCH_END = time(13, 0)


def parse_a_share_timestamp(value: Any) -> Optional[datetime]:
    """Parse a datetime/ISO/efinance string into an Asia/Shanghai aware datetime."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        dt = _parse_string(raw)
        if dt is None:
            return None
    else:
        # pandas Timestamp and similar expose isoformat / to_pydatetime.
        to_py = getattr(value, "to_pydatetime", None)
        if callable(to_py):
            try:
                dt = to_py()
            except Exception:
                return None
        else:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ASIA_SHANGHAI)
    return dt.astimezone(ASIA_SHANGHAI)


def _parse_string(raw: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y%m%d%H%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def is_lunch_break_time(dt: datetime) -> bool:
    """Return whether a timezone-aware datetime falls inside the lunch break."""
    local = dt.astimezone(ASIA_SHANGHAI).time()
    return _LUNCH_START < local < _LUNCH_END
