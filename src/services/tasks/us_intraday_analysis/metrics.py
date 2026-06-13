# -*- coding: utf-8 -*-
"""Derive intraday strength/volume/VWAP metrics from normalized bars."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Optional, Sequence

from data_provider.realtime_types import UnifiedRealtimeQuote, safe_float

from .bars import aggregate_bars
from .market_calendar import parse_timestamp


def compute_intraday_metrics(
    symbol: str,
    bars_1m: Sequence[Dict[str, Any]],
    quote: Optional[UnifiedRealtimeQuote],
    benchmark_metrics: Optional[Dict[str, Any]] = None,
    sector_metrics: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compute the full metric snapshot used by rules, the LLM and rendering."""
    bars_5m = aggregate_bars(bars_1m, 5)
    bars_15m = aggregate_bars(bars_1m, 15)

    latest_price = safe_float(getattr(quote, "price", None)) if quote is not None else None
    if latest_price is None and bars_1m:
        latest_price = safe_float(bars_1m[-1].get("close"))

    vwap_value = _vwap(bars_1m)
    intraday_high = max((float(bar["high"]) for bar in bars_1m), default=None)
    intraday_low = min((float(bar["low"]) for bar in bars_1m), default=None)
    high_distance_pct = None
    if latest_price is not None and intraday_high and intraday_high > 0:
        high_distance_pct = round((intraday_high - latest_price) / intraday_high * 100, 4)

    change_5m = _change_over_minutes(bars_1m, 5)
    change_15m = _change_over_minutes(bars_1m, 15)
    change_60m = _change_over_minutes(bars_1m, 60)
    first_hour = _first_hour_change(bars_1m)

    relative_to_qqq_15m, early_relative_to_qqq = _relative_to_benchmark(
        change_15m, first_hour, benchmark_metrics or {}
    )
    relative_to_sector_15m = _relative_to_sectors(change_15m, sector_metrics or {})

    price_above_vwap = bool(latest_price is not None and vwap_value is not None and latest_price > vwap_value)
    price_below_vwap = bool(latest_price is not None and vwap_value is not None and latest_price < vwap_value)

    return {
        "symbol": symbol,
        "price": latest_price,
        "change_5m": change_5m,
        "change_15m": change_15m,
        "change_60m": change_60m,
        "first_hour_change": first_hour,
        "volume_ratio_5m": _volume_ratio_5m(bars_5m),
        "vwap": vwap_value,
        "price_above_vwap": price_above_vwap,
        "price_below_vwap": price_below_vwap,
        "crossed_above_vwap": _crossed_above_vwap(bars_1m, vwap_value),
        "crossed_below_vwap": _crossed_below_vwap(bars_1m, vwap_value),
        "intraday_high": intraday_high,
        "intraday_low": intraday_low,
        "near_intraday_high": bool(high_distance_pct is not None and high_distance_pct <= 0.25),
        "high_distance_pct": high_distance_pct,
        "relative_to_qqq_15m": relative_to_qqq_15m,
        "early_relative_to_qqq": early_relative_to_qqq,
        "relative_to_sector_15m": relative_to_sector_15m,
        "bars_count_1m": len(bars_1m),
        "bars_count_5m": len(bars_5m),
        "bars_count_15m": len(bars_15m),
        "latest_bar_time": bars_1m[-1]["timestamp"] if bars_1m else None,
        "quote": quote_to_dict(quote),
    }


def quote_to_dict(quote: Optional[UnifiedRealtimeQuote]) -> Dict[str, Any]:
    """Flatten a realtime quote into a JSON-serializable dict."""
    if quote is None:
        return {}
    return {
        "price": safe_float(getattr(quote, "price", None)),
        "change_pct": safe_float(getattr(quote, "change_pct", None)),
        "volume": int(getattr(quote, "volume", 0) or 0),
        "open_price": safe_float(getattr(quote, "open_price", None)),
        "high": safe_float(getattr(quote, "high", None)),
        "low": safe_float(getattr(quote, "low", None)),
        "pre_close": safe_float(getattr(quote, "pre_close", None)),
        "source": getattr(getattr(quote, "source", None), "value", str(getattr(quote, "source", ""))),
    }


def _relative_to_benchmark(
    change_15m: Optional[float],
    first_hour: Optional[float],
    benchmark_metrics: Dict[str, Any],
) -> tuple[Optional[float], Optional[float]]:
    qqq_change_15m = safe_float(benchmark_metrics.get("change_15m"))
    qqq_first_hour = safe_float(benchmark_metrics.get("first_hour_change"))

    relative_to_qqq_15m = None
    if change_15m is not None and qqq_change_15m is not None:
        relative_to_qqq_15m = round(change_15m - qqq_change_15m, 4)

    early_relative_to_qqq = None
    if first_hour is not None and qqq_first_hour is not None:
        early_relative_to_qqq = round(first_hour - qqq_first_hour, 4)

    return relative_to_qqq_15m, early_relative_to_qqq


def _relative_to_sectors(
    change_15m: Optional[float],
    sector_metrics: Dict[str, Dict[str, Any]],
) -> Dict[str, Optional[float]]:
    relative: Dict[str, Optional[float]] = {}
    for sector_symbol, metrics in sector_metrics.items():
        sector_change = safe_float(metrics.get("change_15m"))
        relative[sector_symbol] = (
            round(change_15m - sector_change, 4)
            if change_15m is not None and sector_change is not None
            else None
        )
    return relative


def _pct_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None or previous <= 0:
        return None
    return round((current - previous) / previous * 100, 4)


def _change_over_minutes(bars: Sequence[Dict[str, Any]], minutes: int) -> Optional[float]:
    if len(bars) < 2:
        return None
    latest_ts = parse_timestamp(bars[-1].get("timestamp"))
    if latest_ts is None:
        return None
    cutoff = latest_ts - timedelta(minutes=minutes)
    baseline = None
    for bar in reversed(bars[:-1]):
        ts = parse_timestamp(bar.get("timestamp"))
        if ts is not None and ts <= cutoff:
            baseline = safe_float(bar.get("close"))
            break
    if baseline is None:
        baseline = safe_float(bars[0].get("open"))
    return _pct_change(safe_float(bars[-1].get("close")), baseline)


def _volume_ratio_5m(bars_5m: Sequence[Dict[str, Any]], lookback: int = 12) -> Optional[float]:
    if len(bars_5m) < 3:
        return None
    current_volume = int(bars_5m[-1].get("volume") or 0)
    previous = [
        int(bar.get("volume") or 0)
        for bar in bars_5m[-lookback - 1:-1]
        if int(bar.get("volume") or 0) > 0
    ]
    if not previous:
        return None
    avg_volume = sum(previous) / len(previous)
    if avg_volume <= 0:
        return None
    return round(current_volume / avg_volume, 4)


def _vwap(bars: Sequence[Dict[str, Any]]) -> Optional[float]:
    total_volume = 0
    total_value = 0.0
    for bar in bars:
        volume = int(bar.get("volume") or 0)
        if volume <= 0:
            continue
        turnover = safe_float(bar.get("turnover"))
        if turnover is not None and turnover > 0:
            value = turnover
        else:
            typical = (float(bar["high"]) + float(bar["low"]) + float(bar["close"])) / 3
            value = typical * volume
        total_volume += volume
        total_value += value
    if total_volume <= 0:
        return None
    return round(total_value / total_volume, 4)


def _first_hour_change(bars: Sequence[Dict[str, Any]]) -> Optional[float]:
    if len(bars) < 2:
        return None
    first_ts = parse_timestamp(bars[0].get("timestamp"))
    if first_ts is None:
        return None
    end = first_ts + timedelta(minutes=60)
    last_in_window = None
    for bar in bars:
        ts = parse_timestamp(bar.get("timestamp"))
        if ts is not None and ts <= end:
            last_in_window = bar
    if last_in_window is None:
        return None
    return _pct_change(safe_float(last_in_window.get("close")), safe_float(bars[0].get("open")))


def _crossed_above_vwap(bars: Sequence[Dict[str, Any]], vwap_value: Optional[float]) -> bool:
    if vwap_value is None or len(bars) < 2:
        return False
    previous = safe_float(bars[-2].get("close"))
    current = safe_float(bars[-1].get("close"))
    return bool(previous is not None and current is not None and previous < vwap_value <= current)


def _crossed_below_vwap(bars: Sequence[Dict[str, Any]], vwap_value: Optional[float]) -> bool:
    if vwap_value is None or len(bars) < 2:
        return False
    previous = safe_float(bars[-2].get("close"))
    current = safe_float(bars[-1].get("close"))
    return bool(previous is not None and current is not None and previous > vwap_value >= current)
