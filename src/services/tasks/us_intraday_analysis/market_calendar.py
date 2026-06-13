# -*- coding: utf-8 -*-
"""US market session helpers and timezone-aware timestamp parsing."""

from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Any, Optional

from .config import US_EASTERN

logger = logging.getLogger(__name__)


def is_us_market_open(now: Optional[datetime] = None) -> bool:
    """Return whether ``now`` falls within regular US market hours."""
    current = now or datetime.now(US_EASTERN)
    if current.tzinfo is None:
        current = current.replace(tzinfo=US_EASTERN)
    current = current.astimezone(US_EASTERN)

    try:
        import exchange_calendars as xcals

        calendar = xcals.get_calendar("XNYS")
        return bool(calendar.is_open_on_minute(current, ignore_breaks=True))
    except Exception as exc:
        logger.debug("exchange_calendars unavailable for US market-open check: %s", exc)

    if current.weekday() >= 5:
        return False
    return time(9, 30) <= current.time() < time(16, 0)


def get_us_trading_date(now: Optional[datetime] = None) -> str:
    """Return the US/Eastern trading date (ISO format) for ``now``."""
    current = now or datetime.now(US_EASTERN)
    if current.tzinfo is None:
        current = current.replace(tzinfo=US_EASTERN)
    return current.astimezone(US_EASTERN).date().isoformat()


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse a datetime or ISO string into a US/Eastern aware datetime."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=US_EASTERN)
    return dt.astimezone(US_EASTERN)
