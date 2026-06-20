# -*- coding: utf-8 -*-
"""Normalization and time-bucket aggregation of intraday OHLCV bars."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from finance_analysis.integrations.market_data.realtime_types import safe_float

from .market_calendar import parse_timestamp


def normalize_bars(raw_bars: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate raw bars and return them sorted ascending by timestamp."""
    bars = [_normalize_bar(bar) for bar in raw_bars]
    return sorted((bar for bar in bars if bar is not None), key=lambda item: item["timestamp"])


def aggregate_bars(bars: Sequence[Dict[str, Any]], interval_minutes: int) -> List[Dict[str, Any]]:
    """Aggregate normalized 1-minute bars into N-minute OHLCV bars."""
    if interval_minutes <= 1:
        return list(bars)

    grouped: Dict[datetime, List[Dict[str, Any]]] = {}
    for bar in bars:
        ts = parse_timestamp(bar.get("timestamp"))
        if ts is None:
            continue
        bucket_minute = (ts.minute // interval_minutes) * interval_minutes
        bucket = ts.replace(minute=bucket_minute, second=0, microsecond=0)
        grouped.setdefault(bucket, []).append(bar)

    aggregated: List[Dict[str, Any]] = []
    for bucket in sorted(grouped):
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
