"""Validation for normalized unadjusted daily OHLCV rows."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

import pandas as pd


@dataclass(frozen=True)
class MarketDataValidationError(ValueError):
    reasons: tuple[str, ...]

    def __str__(self) -> str:
        return f"Invalid daily market data: {'; '.join(self.reasons[:10])}"


def _number(value: Any, field: str, row_key: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{row_key}: {field} is not numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{row_key}: {field} is not finite")
    return number


def validate_daily_bars(frame: pd.DataFrame, requested_days: Iterable[date]) -> list[dict[str, Any]]:
    target = set(requested_days)
    reasons: list[str] = []
    valid: list[dict[str, Any]] = []
    seen: set[date] = set()
    for index, raw in enumerate((frame if frame is not None else pd.DataFrame()).to_dict(orient="records")):
        try:
            if "amount" not in raw:
                raise ValueError("amount field is missing")
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
            row = dict(raw)
            for field in ("open", "high", "low", "close"):
                row[field] = _number(raw.get(field), field, bar_date)
                if row[field] <= 0:
                    raise ValueError(f"{bar_date}: {field} must be positive")
            if row["high"] < max(row["open"], row["low"], row["close"]):
                raise ValueError(f"{bar_date}: high is below OHLC values")
            if row["low"] > min(row["open"], row["close"]):
                raise ValueError(f"{bar_date}: low is above open/close")
            row["volume"] = _number(raw.get("volume"), "volume", bar_date)
            if row["volume"] < 0:
                raise ValueError(f"{bar_date}: volume must be non-negative")
            amount = raw.get("amount")
            if amount is None or pd.isna(amount):
                row["amount"] = None
            else:
                row["amount"] = _number(amount, "amount", bar_date)
                if row["amount"] < 0:
                    raise ValueError(f"{bar_date}: amount must be non-negative")
            row["date"] = bar_date
            valid.append(row)
        except Exception as exc:
            reasons.append(f"row={index} {exc}")
    if reasons:
        raise MarketDataValidationError(tuple(reasons))
    return sorted(valid, key=lambda row: row["date"])


def missing_daily_days(rows: Iterable[dict[str, Any]], requested_days: Iterable[date]) -> list[date]:
    actual = {row["date"] for row in rows}
    return sorted(set(requested_days) - actual)


__all__ = ["MarketDataValidationError", "missing_daily_days", "validate_daily_bars"]
