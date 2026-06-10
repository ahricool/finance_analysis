# -*- coding: utf-8 -*-
"""Timezone helpers shared by API and persistence code."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DISPLAY_TIMEZONES = frozenset({"Asia/Shanghai", "America/New_York"})
DEFAULT_DISPLAY_TIMEZONE = "Asia/Shanghai"


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for real instant columns."""
    return datetime.now(timezone.utc)


def ensure_aware_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Normalize an aware datetime to UTC; treat naive datetimes as invalid."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include timezone information")
    return value.astimezone(timezone.utc)


def coerce_aware_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Normalize datetime to UTC; legacy naive values are explicitly treated as UTC."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utc_isoformat(value: Optional[datetime]) -> Optional[str]:
    """Serialize a datetime as ISO 8601 UTC with milliseconds and a trailing Z."""
    normalized = coerce_aware_utc(value)
    if normalized is None:
        return None
    return normalized.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def validate_display_timezone(value: Optional[str]) -> str:
    """Return a supported IANA display timezone name."""
    timezone_name = (value or DEFAULT_DISPLAY_TIMEZONE).strip()
    if timezone_name not in DISPLAY_TIMEZONES:
        raise ValueError(
            f"timezone must be one of: {', '.join(sorted(DISPLAY_TIMEZONES))}"
        )
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:  # pragma: no cover - system tzdata issue
        raise ValueError(f"unknown timezone: {timezone_name}") from exc
    return timezone_name


def day_bounds_utc(day: date, timezone_name: str) -> Tuple[datetime, datetime]:
    """Return [start, end) UTC bounds for one calendar date in a display timezone."""
    tz = ZoneInfo(validate_display_timezone(timezone_name))
    local_start = datetime.combine(day, time.min, tzinfo=tz)
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def date_range_bounds_utc(
    start_date: Optional[date],
    end_date: Optional[date],
    timezone_name: str,
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Return UTC bounds for an inclusive local-date range."""
    start = day_bounds_utc(start_date, timezone_name)[0] if start_date else None
    end = day_bounds_utc(end_date, timezone_name)[1] if end_date else None
    return start, end
