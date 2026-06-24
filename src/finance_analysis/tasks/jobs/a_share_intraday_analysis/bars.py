# -*- coding: utf-8 -*-
"""Normalization and aggregation of A-share intraday OHLCV minute bars."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from finance_analysis.integrations.market_data.realtime_types import safe_float

from .market_calendar import (
    ASIA_SHANGHAI,
    is_lunch_break_time,
    parse_a_share_timestamp,
)


def normalize_bars(
    raw_bars: Iterable[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Validate, dedupe and sort raw minute bars for an A-share security.

    - converts timestamps to Asia/Shanghai;
    - drops bars stamped inside the lunch break;
    - drops bars stamped in the future (relative to ``now``);
    - removes duplicate timestamps (keeping the last);
    - returns ascending by timestamp.
    """
    cutoff = None
    if now is not None:
        cutoff = now.astimezone(ASIA_SHANGHAI)

    by_ts: Dict[str, Dict[str, Any]] = {}
    for raw in raw_bars:
        bar = _normalize_bar(raw)
        if bar is None:
            continue
        ts = parse_a_share_timestamp(bar["timestamp"])
        if ts is None or is_lunch_break_time(ts):
            continue
        if cutoff is not None and ts > cutoff:
            continue
        by_ts[bar["timestamp"]] = bar
    return sorted(by_ts.values(), key=lambda item: item["timestamp"])


def aggregate_bars(bars: Sequence[Dict[str, Any]], interval_minutes: int) -> List[Dict[str, Any]]:
    """Aggregate normalized 1-minute bars into N-minute OHLCV bars."""
    if interval_minutes <= 1:
        return list(bars)

    grouped: Dict[datetime, List[Dict[str, Any]]] = {}
    for bar in bars:
        ts = parse_a_share_timestamp(bar.get("timestamp"))
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
    ts = parse_a_share_timestamp(raw.get("timestamp"))
    close = safe_float(raw.get("close"))
    open_price = safe_float(raw.get("open"))
    high = safe_float(raw.get("high"))
    low = safe_float(raw.get("low"))
    if ts is None or close is None:
        return None
    # Fall back to close when an OHLC field is missing so a usable bar survives.
    open_price = open_price if open_price is not None else close
    high = high if high is not None else max(open_price, close)
    low = low if low is not None else min(open_price, close)
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
