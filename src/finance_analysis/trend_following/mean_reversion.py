"""Independent mean reversion research, with one rebound per oversold episode."""

import numpy as np
import pandas as pd

from finance_analysis.analysis.technical.indicators import rsi_series
from .config import DEFAULT_CONFIG
from .features import true_ranges
from .scoring import gaussian, tanh_quality

MR_NUMERIC_FIELDS = (
    "rsi14",
    "distance_from_ma20_atr",
    "mr_quality",
    "mr_oversold_quality",
    "mr_distance_quality",
    "mr_shock_quality",
    "mr_reversal_quality",
    "mr_previous_rsi14",
)


def calculate_mean_reversion(bars, features, config=DEFAULT_CONFIG, *, previous_features=None):
    """Replay visible history only. A consumed episode rearms after leaving oversold."""
    closes = pd.Series([bar.close for bar in bars], dtype=float)
    rsi = rsi_series(closes, config.mr_rsi_period, wilder=True).to_numpy()
    ma = closes.rolling(20).mean().to_numpy()
    atr = pd.Series(true_ranges(bars)).rolling(20).mean().to_numpy()
    consumed, previous_state, state = False, "MR_NONE", "MR_NONE"
    current_distance = None
    # With an official predecessor only today's transition needs replaying.
    has_previous = previous_features and previous_features.get("mr_state") is not None
    for i in range(len(bars) - 1 if has_previous else 20, len(bars)):
        if i == len(bars) - 1 and has_previous:
            previous_state = previous_features["mr_state"]
            consumed = previous_features.get("mr_episode_consumed", False)
            if previous_features.get("rsi14") is not None:
                rsi[i - 1] = previous_features["rsi14"]
        distance = (closes.iloc[i] - ma[i]) / atr[i] if atr[i] > 0 else None
        if i == len(bars) - 1:
            distance = (
                (features["reference_price"] - features["ma20"]) / features["atr20"] if features["atr20"] > 0 else None
            )
            current_distance = distance
        oversold = (
            distance is not None
            and np.isfinite(rsi[i])
            and rsi[i] <= config.mr_rsi_max
            and distance <= config.mr_distance_max_atr
            and closes.iloc[i] / closes.iloc[i - 5] - 1 < config.mr_return_5d_max
        )
        bar = bars[i]
        clv = (bar.close - bar.low) / (bar.high - bar.low) if bar.high > bar.low else None
        rebound = (
            not consumed
            and previous_state == "MR_OVERSOLD"
            and bar.close > bars[i - 1].close
            and clv is not None
            and clv >= config.mr_rebound_clv_min
            and rsi[i] > rsi[i - 1]
        )
        state = "MR_REBOUND" if rebound else "MR_OVERSOLD" if oversold else "MR_NONE"
        if rebound:
            consumed = True
        if not oversold:
            consumed = False
        previous_state = state
    clv = features.get("close_location_value")
    rsi_now = float(rsi[-1]) if len(rsi) and np.isfinite(rsi[-1]) else None
    components = {
        "oversold": (
            tanh_quality(config.mr_rsi_quality_center - rsi_now, config.mr_rsi_quality_scale)
            if rsi_now is not None
            else 0
        ),
        "distance": (
            100 * gaussian(current_distance, config.mr_distance_center_atr, config.mr_distance_width_atr)
            if current_distance is not None
            else 0
        ),
        "shock": 0.5
        * (
            tanh_quality(-features["return_3d"], config.mr_shock_3d_scale)
            + tanh_quality(-features["return_5d"], config.mr_shock_5d_scale)
        ),
        "reversal": (
            100 * (clv if clv is not None else 0) * max(0, min(1, (rsi[-1] - rsi[-2]) / config.mr_rsi_quality_scale))
            if len(rsi) > 1 and np.isfinite(rsi[-2:]).all()
            else 0
        ),
    }
    return {
        "rsi14": rsi_now,
        "distance_from_ma20_atr": current_distance,
        "mr_previous_rsi14": float(rsi[-2]) if len(rsi) > 1 and np.isfinite(rsi[-2]) else None,
        "mr_state": state,
        "mr_episode_consumed": consumed,
        "mr_quality": sum(components[key] * weight for key, weight in config.mr_quality_weights.items()),
        **{f"mr_{key}_quality": value for key, value in components.items()},
    }
