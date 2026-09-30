"""Independent box structure research. Every candidate ends on T-1."""

from dataclasses import dataclass
from math import exp, sqrt
from typing import Any, Sequence

import numpy as np

from .config import DEFAULT_CONFIG, TrendFollowingConfig
from .models import DailyBar
from .scoring import gaussian, smoothstep, tanh_quality

BOX_NUMERIC_FIELDS = (
    "box_quality",
    "box_window_days",
    "box_high",
    "box_low",
    "box_mid",
    "box_width_pct",
    "box_slope",
    "box_slope_atr",
    "box_r_squared",
    "box_occupancy",
    "box_upper_touches",
    "box_lower_touches",
    "distance_to_box_high_pct",
    "distance_to_box_high_atr",
    "box_breakout_distance_atr",
    "box_atr20",
    "box_width_quality",
    "box_flatness_quality",
    "box_occupancy_quality",
    "box_compression_quality",
    "box_touch_quality",
)
BOX_STRING_FIELDS = ("box_state", "box_start_date", "box_end_date", "box_episode_breakout_date")
BOX_SORT_FIELDS = (
    "box_quality",
    "box_window_days",
    "box_width_pct",
    "distance_to_box_high_pct",
    "distance_to_box_high_atr",
    "box_breakout_distance_atr",
)


@dataclass(frozen=True)
class BoxCandidate:
    days: int
    quality: float
    features: dict[str, Any]


def select_box(candidates: Sequence[BoxCandidate], tolerance: float) -> BoxCandidate:
    """Tie band is relative to the global maximum, never chained pairwise."""
    best = max(candidate.quality for candidate in candidates)
    return max((c for c in candidates if best - c.quality <= tolerance), key=lambda c: c.days)


def _touches(values: np.ndarray) -> int:
    # Consecutive testing days form one visit, not many independent tests.
    return int(np.count_nonzero(values & ~np.r_[False, values[:-1]]))


def calculate_box_structure(
    bars: Sequence[DailyBar],
    prior_atr20: float,
    features: dict[str, Any],
    config: TrendFollowingConfig = DEFAULT_CONFIG,
    *,
    previous_features: dict[str, Any] | None = None,
    preview: bool = False,
) -> dict[str, Any]:
    """bars are ordered through T; ATR/compression are the existing T-1 values."""
    empty = {key: None for key in (*BOX_NUMERIC_FIELDS, *BOX_STRING_FIELDS)}
    empty["box_state"] = "NONE"
    prior = previous_features or {}
    consumed = prior.get("box_episode_consumed", False)
    breakout_date = prior.get("box_episode_breakout_date")
    empty.update(
        box_breakout_fresh=False,
        box_prior_breakout_confirmed=False,
        box_episode_consumed=consumed,
        box_episode_breakout_date=breakout_date,
    )
    if prior_atr20 <= 0:
        return empty
    atr_ratio, range_ratio = features.get("atr_contraction_ratio"), features.get("range_contraction_ratio")
    compression = sqrt(
        (
            tanh_quality(config.atr_compression_center - atr_ratio, config.atr_compression_scale)
            if atr_ratio is not None
            else 0.0
        )
        * (
            tanh_quality(config.range_compression_center - range_ratio, config.range_compression_scale)
            if range_ratio is not None
            else 0.0
        )
    )
    candidates = []
    for days in config.box_windows:
        if days < config.box_min_days or len(bars) <= days:
            continue
        window = bars[-days - 1 : -1]
        high, low = max(b.high for b in window), min(b.low for b in window)
        width, mid = high - low, (high + low) / 2
        if mid <= 0 or width <= 0 or width / mid > config.box_max_width_pct:
            continue
        closes = np.array([b.close for b in window], dtype=float)
        x = np.arange(days, dtype=float)
        x -= x.mean()
        logs = np.log(closes)
        slope = float(np.dot(x, logs - logs.mean()) / np.dot(x, x))
        fitted = logs.mean() + slope * x
        total = float(np.sum((logs - logs.mean()) ** 2))
        r2 = max(0.0, 1 - float(np.sum((logs - fitted) ** 2)) / total) if total > 1e-15 else 1.0
        slope_atr = abs(exp(float(fitted[-1])) - exp(float(fitted[0]))) / prior_atr20
        occupancy = float(
            np.mean(
                (closes >= low + config.box_inner_margin * width) & (closes <= high - config.box_inner_margin * width)
            )
        )
        tolerance = max(config.box_touch_atr_tolerance * prior_atr20, config.box_touch_width_tolerance * width)
        upper = _touches(np.array([b.high >= high - tolerance for b in window]))
        lower = _touches(np.array([b.low <= low + tolerance for b in window]))
        width_pct = width / mid
        components = {
            "width": 100
            * smoothstep(width_pct, config.box_dead_width_pct, config.box_width_plateau_min_pct)
            * (1 - smoothstep(width_pct, config.box_ideal_width_pct, config.box_max_width_pct)),
            "flatness": 100 * gaussian(slope_atr, 0, config.box_flatness_scale_atr),
            "occupancy": 100 * occupancy,
            "compression": compression,
            "touch": 100 * smoothstep(upper, 0, config.box_touch_target),
        }
        quality = sum(components[key] * weight for key, weight in config.box_quality_weights.items())
        candidates.append(
            BoxCandidate(
                days,
                quality,
                {
                    "box_quality": quality,
                    "box_window_days": days,
                    "box_high": high,
                    "box_low": low,
                    "box_mid": mid,
                    "box_width_pct": width_pct,
                    "box_slope": slope,
                    "box_slope_atr": slope_atr,
                    "box_r_squared": r2,
                    "box_occupancy": occupancy,
                    "box_upper_touches": upper,
                    "box_lower_touches": lower,
                    "box_atr20": prior_atr20,
                    "box_start_date": window[0].trade_date.isoformat(),
                    "box_end_date": window[-1].trade_date.isoformat(),
                    **{f"box_{key}_quality": value for key, value in components.items()},
                },
            )
        )
    qualified = [c for c in candidates if c.quality >= config.box_forming_quality_min]
    if not qualified:
        return empty
    selected = select_box(qualified, config.box_quality_tie_tolerance)
    result = selected.features.copy()
    # A complete new structure must lie after the old event. A retest, missing
    # candidate or moving window that still contains the event never rearms it.
    if consumed and breakout_date and result["box_start_date"] > breakout_date and not preview:
        consumed, breakout_date = False, None
    close, high, low = bars[-1].close, result["box_high"], result["box_low"]
    distance = (high - close) / high
    breakout = (close - high) / prior_atr20
    clv = features.get("close_location_value")
    # Yesterday is tested against the selected box excluding yesterday itself.
    # Match yesterday's confirmation basis: ATR ending before yesterday.
    previous = bars[-2]
    resistance = max(bar.high for bar in bars[-selected.days - 1 : -2])
    from .features import true_ranges

    previous_atr = float(np.mean(true_ranges(bars[:-2])[-20:])) if len(bars) >= 22 else None
    previous_z = (previous.close - resistance) / previous_atr if previous_atr and previous_atr > 0 else None
    previous_clv = (
        (previous.close - previous.low) / (previous.high - previous.low) if previous.high > previous.low else None
    )
    prior_confirmed = (
        previous_z is not None
        and config.box_breakout_min_atr <= previous_z <= config.box_breakout_max_atr
        and previous_clv is not None
        and previous_clv >= config.box_breakout_clv_min
    )
    result.update(
        box_prior_breakout_confirmed=prior_confirmed,
        box_previous_resistance=resistance,
        box_previous_breakout_atr=previous_z,
        box_previous_clv=previous_clv,
    )
    state = "NONE"
    if (
        not consumed
        and not prior_confirmed
        and selected.quality >= config.box_breakout_quality_min
        and config.box_breakout_min_atr <= breakout <= config.box_breakout_max_atr
        and clv is not None
        and clv >= config.box_breakout_clv_min
    ):
        state = "BOX_BREAKOUT"
    elif (
        selected.quality >= config.box_ready_quality_min
        and low <= close
        and breakout <= config.box_breakout_min_atr
        and distance <= config.box_ready_distance_pct
    ):
        state = "BOX_READY"
    elif low <= close <= high:
        state = "BOX_FORMING"
    if state == "BOX_BREAKOUT":
        consumed, breakout_date = True, bars[-1].trade_date.isoformat()
    return {
        **result,
        "box_episode_consumed": consumed,
        "box_episode_breakout_date": breakout_date,
        "box_state": state,
        "box_breakout_fresh": state == "BOX_BREAKOUT",
        "distance_to_box_high_pct": distance,
        "distance_to_box_high_atr": -breakout,
        "box_breakout_distance_atr": breakout,
    }
