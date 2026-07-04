"""Normalization, bar validation, and exchange-session completeness checks."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from finance_analysis.market_review.trading_calendar import get_market_session_bounds

NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class MarketDataValidationError(ValueError):
    data_type: str
    reasons: tuple[str, ...]

    def __str__(self) -> str:
        return f"Invalid {self.data_type} market data: {'; '.join(self.reasons[:10])}"


def _number(value: Any, field: str, row_key: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{row_key}: {field} is not numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{row_key}: {field} is not finite")
    return number


def _validate_prices(row: dict[str, Any], key: Any) -> dict[str, Any]:
    result = dict(row)
    for field in ("open", "high", "low", "close"):
        result[field] = _number(row.get(field), field, key)
        if result[field] <= 0:
            raise ValueError(f"{key}: {field} must be positive")
    if result["high"] < max(result["open"], result["low"], result["close"]):
        raise ValueError(f"{key}: high is below OHLC values")
    if result["low"] > min(result["open"], result["close"]):
        raise ValueError(f"{key}: low is above open/close")
    result["volume"] = _number(row.get("volume"), "volume", key)
    if result["volume"] < 0:
        raise ValueError(f"{key}: volume must be non-negative")
    amount = row.get("amount")
    if amount is None or pd.isna(amount):
        result["amount"] = None
    else:
        result["amount"] = _number(amount, "amount", key)
        if result["amount"] < 0:
            raise ValueError(f"{key}: amount must be non-negative")
    return result


def validate_daily_bars(frame: pd.DataFrame, requested_days: Iterable[date]) -> list[dict[str, Any]]:
    target = set(requested_days)
    reasons: list[str] = []
    valid: list[dict[str, Any]] = []
    seen: set[date] = set()
    for index, raw in enumerate((frame if frame is not None else pd.DataFrame()).to_dict(orient="records")):
        try:
            value = raw.get("date")
            if isinstance(value, datetime):
                bar_date = value.date()
            elif isinstance(value, date):
                bar_date = value
            else:
                bar_date = pd.Timestamp(value).date()
            if bar_date not in target:
                continue
            if bar_date in seen:
                raise ValueError(f"{bar_date}: duplicate date")
            seen.add(bar_date)
            row = _validate_prices(raw, bar_date)
            row["date"] = bar_date
            valid.append(row)
        except Exception as exc:
            reasons.append(f"row={index} {exc}")
    if reasons:
        raise MarketDataValidationError("daily", tuple(reasons))
    return sorted(valid, key=lambda row: row["date"])


def expected_minute_times(trading_day: date) -> set[datetime]:
    session_open, session_close = get_market_session_bounds("us", trading_day)
    cursor = session_open.replace(second=0, microsecond=0)
    expected: set[datetime] = set()
    while cursor < session_close:
        expected.add(cursor.astimezone(timezone.utc))
        cursor += timedelta(minutes=1)
    return expected


def validate_minute_bars(
    frame: pd.DataFrame,
    trading_day: date,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    session_open, session_close = get_market_session_bounds("us", trading_day)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    reasons: list[str] = []
    by_time: dict[datetime, dict[str, Any]] = {}
    for index, raw in enumerate((frame if frame is not None else pd.DataFrame()).to_dict(orient="records")):
        try:
            value = raw.get("bar_time")
            timestamp = pd.Timestamp(value)
            if timestamp.tzinfo is None:
                raise ValueError("bar_time must be timezone-aware")
            utc_time = timestamp.to_pydatetime().astimezone(timezone.utc)
            if utc_time.second or utc_time.microsecond:
                raise ValueError(f"{utc_time}: bar_time is not minute-aligned")
            local = utc_time.astimezone(NEW_YORK)
            if local.date() != trading_day:
                continue
            if not (session_open <= local < session_close):
                continue
            if utc_time + timedelta(minutes=1) > current:
                continue
            row = _validate_prices(raw, utc_time)
            row["bar_time"] = utc_time
            # Provider duplicates are deterministically collapsed before persistence.
            by_time[utc_time] = row
        except Exception as exc:
            reasons.append(f"row={index} {exc}")
    if reasons:
        raise MarketDataValidationError("minute", tuple(reasons))
    return [by_time[key] for key in sorted(by_time)]


def missing_daily_days(rows: Iterable[dict[str, Any]], requested_days: Iterable[date]) -> list[date]:
    actual = {row["date"] for row in rows}
    return sorted(set(requested_days) - actual)


def missing_minute_times(rows: Iterable[dict[str, Any]], trading_day: date) -> list[datetime]:
    actual = {row["bar_time"] for row in rows}
    return sorted(expected_minute_times(trading_day) - actual)

