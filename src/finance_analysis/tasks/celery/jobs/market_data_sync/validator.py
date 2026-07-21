"""Validation for normalized unadjusted daily OHLCV rows."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

import pandas as pd

PROVIDER_VWAP_SOURCES = {
    "LongbridgeFetcher": "longbridge",
    "EfinanceFetcher": "efinance",
    "AkshareFetcher": "akshare",
    "YfinanceFetcher": "yfinance",
}


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


def validate_daily_bars(
    frame: pd.DataFrame,
    requested_days: Iterable[date],
    *,
    invalid_reasons: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return valid requested rows while isolating malformed provider records."""
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
            seen.add(bar_date)
            valid.append(row)
        except Exception as exc:
            reasons.append(f"row={index} {exc}")
    if invalid_reasons is not None:
        invalid_reasons.extend(reasons)
    return sorted(valid, key=lambda row: row["date"])


def missing_daily_days(rows: Iterable[dict[str, Any]], requested_days: Iterable[date]) -> list[date]:
    actual = {row["date"] for row in rows}
    return sorted(set(requested_days) - actual)


def enrich_daily_vwap(rows: Iterable[dict[str, Any]], provider: str) -> list[dict[str, Any]]:
    """Set VWAP once per provider row without synthesizing turnover."""
    enriched: list[dict[str, Any]] = []
    provider_source = PROVIDER_VWAP_SOURCES.get(provider, provider.lower())
    for raw in rows:
        row = dict(raw)
        vwap = _optional_positive_number(row.get("vwap"))
        if vwap is not None:
            row.update(vwap=vwap, vwap_source=provider_source, vwap_quality="provider")
            enriched.append(row)
            continue

        amount = _optional_nonnegative_number(row.get("amount"))
        volume = _optional_nonnegative_number(row.get("volume"))
        if amount is not None and volume is not None and volume > 0:
            calculated = amount / volume
            if math.isfinite(calculated) and calculated > 0:
                row.update(vwap=calculated, vwap_source="amount_div_volume", vwap_quality="calculated")
                enriched.append(row)
                continue

        high = _optional_positive_number(row.get("high"))
        low = _optional_positive_number(row.get("low"))
        close = _optional_positive_number(row.get("close"))
        if high is not None and low is not None and close is not None:
            row.update(vwap=(high + low + close) / 3.0, vwap_source="hlc3", vwap_quality="estimated")
        else:
            row.update(vwap=None, vwap_source=None, vwap_quality="missing")
        enriched.append(row)
    return enriched


def _optional_positive_number(value: Any) -> float | None:
    number = _optional_nonnegative_number(value)
    return number if number is not None and number > 0 else None


def _optional_nonnegative_number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


__all__ = ["MarketDataValidationError", "enrich_daily_vwap", "missing_daily_days", "validate_daily_bars"]
