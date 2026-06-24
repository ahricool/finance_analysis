# -*- coding: utf-8 -*-
"""Derive A-share intraday strength / volume / VWAP / limit metrics."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Optional, Sequence

from finance_analysis.integrations.market_data.realtime_types import (
    UnifiedRealtimeQuote,
    safe_float,
)

from .bars import aggregate_bars
from .market_calendar import parse_a_share_timestamp
from .price_limits import PriceLimitRule

# Tolerance for treating a price as "at the limit" (relative).
_LIMIT_TOLERANCE_PCT = 0.05


def compute_a_share_intraday_metrics(
    *,
    code: str,
    name: str,
    board: str,
    bars_1m: Sequence[Dict[str, Any]],
    quote: Optional[UnifiedRealtimeQuote],
    snapshot: Optional[Dict[str, Any]],
    price_limit: PriceLimitRule,
    main_index_metrics: Optional[Dict[str, Any]] = None,
    board_index_metrics: Optional[Dict[str, Any]] = None,
    sector_change_15m: Optional[float] = None,
    data_source: str = "",
) -> Dict[str, Any]:
    """Compute the full intraday metric snapshot for a candidate."""
    snapshot = snapshot or {}
    bars_5m = aggregate_bars(bars_1m, 5)
    bars_15m = aggregate_bars(bars_1m, 15)

    pre_close = safe_float(snapshot.get("pre_close"))
    if pre_close is None and quote is not None:
        pre_close = safe_float(getattr(quote, "pre_close", None))

    open_price = safe_float(snapshot.get("open"))
    if open_price is None and quote is not None:
        open_price = safe_float(getattr(quote, "open_price", None))
    if open_price is None and bars_1m:
        open_price = safe_float(bars_1m[0].get("open"))

    price = safe_float(getattr(quote, "price", None)) if quote is not None else None
    if price is None:
        price = safe_float(snapshot.get("price"))
    if price is None and bars_1m:
        price = safe_float(bars_1m[-1].get("close"))

    change_pct = _pct_change(price, pre_close)
    if change_pct is None:
        change_pct = safe_float(snapshot.get("change_pct"))
    opening_gap_pct = _pct_change(open_price, pre_close)

    vwap_value = _vwap(bars_1m)
    intraday_high = max((float(bar["high"]) for bar in bars_1m), default=None)
    intraday_low = min((float(bar["low"]) for bar in bars_1m), default=None)
    drawdown_from_high = None
    if price is not None and intraday_high and intraday_high > 0:
        drawdown_from_high = round((intraday_high - price) / intraday_high * 100, 4)
    rebound_from_low = None
    if price is not None and intraday_low and intraday_low > 0:
        rebound_from_low = round((price - intraday_low) / intraday_low * 100, 4)

    change_5m = _change_over_minutes(bars_1m, 5)
    change_15m = _change_over_minutes(bars_1m, 15)
    change_30m = _change_over_minutes(bars_1m, 30)
    change_60m = _change_over_minutes(bars_1m, 60)

    relative_main = _relative(change_15m, (main_index_metrics or {}).get("change_15m"))
    relative_board = _relative(change_15m, (board_index_metrics or {}).get("change_15m"))
    relative_sector = _relative(change_15m, sector_change_15m)

    price_above_vwap = bool(price is not None and vwap_value is not None and price > vwap_value)
    price_below_vwap = bool(price is not None and vwap_value is not None and price < vwap_value)

    limit_metrics = _limit_metrics(price, intraday_high, intraday_low, open_price, price_limit)

    return {
        "code": code,
        "name": name,
        "board": board,
        "price": price,
        "pre_close": pre_close,
        "open": open_price,
        "change_pct": change_pct,
        "opening_gap_pct": opening_gap_pct,
        "change_5m": change_5m,
        "change_15m": change_15m,
        "change_30m": change_30m,
        "change_60m": change_60m,
        "vwap": vwap_value,
        "price_above_vwap": price_above_vwap,
        "price_below_vwap": price_below_vwap,
        "crossed_above_vwap": _crossed_above_vwap(bars_1m, vwap_value),
        "crossed_below_vwap": _crossed_below_vwap(bars_1m, vwap_value),
        "intraday_high": intraday_high,
        "intraday_low": intraday_low,
        "drawdown_from_high_pct": drawdown_from_high,
        "rebound_from_low_pct": rebound_from_low,
        "intraday_volume_ratio": _intraday_volume_ratio(bars_5m),
        "amount_5m": _amount_over(bars_5m, 1),
        "amount_15m": _amount_over(bars_5m, 3),
        "turnover_rate": safe_float(snapshot.get("turnover_rate")),
        "amplitude": safe_float(snapshot.get("amplitude")),
        "relative_to_main_index_15m": relative_main,
        "relative_to_board_index_15m": relative_board,
        "relative_to_sector_15m": relative_sector,
        "bars_count": len(bars_1m),
        "bars_count_5m": len(bars_5m),
        "bars_count_15m": len(bars_15m),
        "latest_bar_time": bars_1m[-1]["timestamp"] if bars_1m else None,
        "data_source": data_source,
        **limit_metrics,
    }


def _limit_metrics(
    price: Optional[float],
    intraday_high: Optional[float],
    intraday_low: Optional[float],
    open_price: Optional[float],
    rule: PriceLimitRule,
) -> Dict[str, Any]:
    limit_up = rule.limit_up_price
    limit_down = rule.limit_down_price
    metrics: Dict[str, Any] = {
        "has_price_limit": rule.has_price_limit,
        "limit_board": rule.board,
        "limit_up_price": limit_up,
        "limit_down_price": limit_down,
        "limit_ratio": rule.limit_ratio,
        "distance_to_limit_up_pct": None,
        "distance_to_limit_down_pct": None,
        "is_limit_up": False,
        "is_limit_down": False,
        "touched_limit_up": False,
        "touched_limit_down": False,
        "opened_from_limit_up": False,
        "opened_from_limit_down": False,
    }
    if limit_up and limit_up > 0:
        if price is not None:
            metrics["distance_to_limit_up_pct"] = round((limit_up - price) / limit_up * 100, 4)
            metrics["is_limit_up"] = _at_limit(price, limit_up)
        if intraday_high is not None:
            metrics["touched_limit_up"] = _at_limit(intraday_high, limit_up) or intraday_high >= limit_up
        metrics["opened_from_limit_up"] = bool(
            metrics["touched_limit_up"] and not metrics["is_limit_up"]
        )
    if limit_down and limit_down > 0:
        if price is not None:
            metrics["distance_to_limit_down_pct"] = round((price - limit_down) / limit_down * 100, 4)
            metrics["is_limit_down"] = _at_limit(price, limit_down)
        if intraday_low is not None:
            metrics["touched_limit_down"] = _at_limit(intraday_low, limit_down) or intraday_low <= limit_down
        metrics["opened_from_limit_down"] = bool(
            metrics["touched_limit_down"] and not metrics["is_limit_down"]
        )
    # One-word board: opened at the limit and never left it.
    metrics["one_word_limit_up"] = bool(
        metrics["is_limit_up"]
        and open_price is not None
        and limit_up
        and _at_limit(open_price, limit_up)
    )
    return metrics


def _at_limit(value: float, limit_price: float) -> bool:
    if limit_price <= 0:
        return False
    return abs(value - limit_price) / limit_price * 100 <= _LIMIT_TOLERANCE_PCT


def _relative(change_15m: Optional[float], benchmark_change: Optional[float]) -> Optional[float]:
    a = safe_float(change_15m)
    b = safe_float(benchmark_change)
    if a is None or b is None:
        return None
    return round(a - b, 4)


def _pct_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    current = safe_float(current)
    previous = safe_float(previous)
    if current is None or previous is None or previous <= 0:
        return None
    return round((current - previous) / previous * 100, 4)


def _change_over_minutes(bars: Sequence[Dict[str, Any]], minutes: int) -> Optional[float]:
    if len(bars) < 2:
        return None
    latest_ts = parse_a_share_timestamp(bars[-1].get("timestamp"))
    if latest_ts is None:
        return None
    cutoff = latest_ts - timedelta(minutes=minutes)
    baseline = None
    for bar in reversed(bars[:-1]):
        ts = parse_a_share_timestamp(bar.get("timestamp"))
        if ts is not None and ts <= cutoff:
            baseline = safe_float(bar.get("close"))
            break
    if baseline is None:
        baseline = safe_float(bars[0].get("open"))
    return _pct_change(safe_float(bars[-1].get("close")), baseline)


def _intraday_volume_ratio(bars_5m: Sequence[Dict[str, Any]], lookback: int = 6) -> Optional[float]:
    """Current 5m volume vs the average of the preceding 5m windows (intraday)."""
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


def _amount_over(bars_5m: Sequence[Dict[str, Any]], windows: int) -> Optional[float]:
    if not bars_5m:
        return None
    selected = bars_5m[-windows:]
    values = [safe_float(bar.get("turnover")) for bar in selected]
    if not any(v is not None for v in values):
        return None
    return round(sum(v for v in values if v is not None), 4)


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
