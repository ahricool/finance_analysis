# -*- coding: utf-8 -*-
"""Normalization and time-bucket aggregation of intraday OHLCV bars."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

from finance_analysis.integrations.market_data.realtime_types import safe_float

from .config import US_EASTERN
from .market_calendar import parse_timestamp


def normalize_bars(raw_bars: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate raw bars and return them sorted ascending by timestamp."""
    bars = [_normalize_bar(bar) for bar in raw_bars]
    return sorted((bar for bar in bars if bar is not None), key=lambda item: item["timestamp"])


def aggregate_bars(
    bars: Sequence[Dict[str, Any]],
    interval_minutes: int,
    *,
    now: Optional[datetime] = None,
    complete_only: bool = False,
) -> List[Dict[str, Any]]:
    """Aggregate normalized 1-minute bars into N-minute OHLCV bars.

    When ``complete_only`` is true, buckets whose end time is after ``now`` in
    America/New_York are omitted. Buckets are also keyed by the parsed Eastern
    timestamp, so aggregation never merges bars from different trading dates.
    """
    if interval_minutes <= 1:
        if not complete_only:
            return list(bars)
        current = _eastern_now(now)
        return [
            bar
            for bar in bars
            if (ts := parse_timestamp(bar.get("timestamp"))) is not None
            and ts + timedelta(minutes=1) <= current
        ]

    grouped: Dict[datetime, List[Dict[str, Any]]] = {}
    for bar in bars:
        ts = parse_timestamp(bar.get("timestamp"))
        if ts is None:
            continue
        bucket_minute = (ts.minute // interval_minutes) * interval_minutes
        bucket = ts.replace(minute=bucket_minute, second=0, microsecond=0)
        grouped.setdefault(bucket, []).append(bar)

    current = _eastern_now(now) if complete_only else None
    aggregated: List[Dict[str, Any]] = []
    for bucket in sorted(grouped):
        if current is not None and bucket + timedelta(minutes=interval_minutes) > current:
            continue
        items = sorted(grouped[bucket], key=lambda item: item["timestamp"])
        aggregated.append(
            {
                "timestamp": bucket.isoformat(),
                "open": items[0]["open"],
                "high": max(item["high"] for item in items),
                "low": min(item["low"] for item in items),
                "close": items[-1]["close"],
                "volume": sum(int(item.get("volume") or 0) for item in items),
                "turnover": _sum_turnover(items),
            }
        )
    return aggregated


def _eastern_now(now: Optional[datetime] = None) -> datetime:
    current = now or datetime.now(US_EASTERN)
    if current.tzinfo is None:
        current = current.replace(tzinfo=US_EASTERN)
    return current.astimezone(US_EASTERN)


def _normalize_bar(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    ts = parse_timestamp(raw.get("timestamp"))
    close = safe_float(raw.get("close"))
    open_price = safe_float(raw.get("open"))
    high = safe_float(raw.get("high"))
    low = safe_float(raw.get("low"))
    if ts is None or close is None or open_price is None or high is None or low is None:
        return None
    return {
        "timestamp": ts.isoformat(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": int(raw.get("volume") or 0),
        "turnover": safe_float(raw.get("turnover")),
    }


def _sum_turnover(items: Sequence[Dict[str, Any]]) -> Optional[float]:
    values = [safe_float(item.get("turnover")) for item in items]
    if not any(v is not None for v in values):
        return None
    return sum(v for v in values if v is not None)
