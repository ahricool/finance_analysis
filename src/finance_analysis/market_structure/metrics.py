"""Pure closing metrics. Missing observations stay missing, never become zero."""

import math
from statistics import median

import numpy as np

from finance_analysis.trend_following.features import percentile_ranks
from .config import DEFAULT_CONFIG


def leadership(returns, config=DEFAULT_CONFIG):
    values = sorted((max(float(value), 0.0) for value in returns), reverse=True)
    size, total = len(values), sum(values)
    if not size or total <= 0:
        return None, None
    contribution = sum(values[: max(1, math.ceil(size * config.top_fraction))]) / total
    raw = sum((value / total) ** 2 for value in values)
    hhi = 1.0 if size == 1 else (raw - 1 / size) / (1 - 1 / size)
    return contribution, max(0.0, min(100.0, hhi * 100))


def rotation_velocity(current, previous):
    # Strict membership equality prevents universe churn being mistaken for rotation.
    if len(current) < 2 or set(current) != set(previous):
        return None
    codes = sorted(current)
    if any(current[c] is None or previous[c] is None for c in codes):
        return None
    left = np.asarray(percentile_ranks(current[c] for c in codes))
    right = np.asarray(percentile_ranks(previous[c] for c in codes))
    if np.std(left) == 0 or np.std(right) == 0:
        return None
    rho = float(np.corrcoef(left, right)[0, 1])
    return max(0.0, min(100.0, (1 - rho) * 50))


def rotation_metrics(snapshots, trade_date):
    dates = sorted((d for d in snapshots if d <= trade_date), reverse=True)
    result = {f"rotation_velocity_{n}d": None for n in (1, 3, 5)}
    if not dates or dates[0] != trade_date:
        return result
    for n in (1, 3, 5):
        if len(dates) > n:
            result[f"rotation_velocity_{n}d"] = rotation_velocity(snapshots[trade_date], snapshots[dates[n]])
    return result


def breadth(benchmark_return, returns):
    center = median(returns)
    return {
        "benchmark_return_5d": benchmark_return,
        "median_member_return_5d": center,
        "breadth_divergence_5d": benchmark_return - center,
        "member_positive_ratio_5d": sum(value > 0 for value in returns) / len(returns),
    }


def states(metrics, config=DEFAULT_CONFIG):
    divergence = metrics["breadth_divergence_5d"]
    positive = metrics["member_positive_ratio_5d"]
    rising = metrics["benchmark_return_5d"] > 0
    breadth_state = (
        "STRONG_DIVERGENCE"
        if rising and divergence >= config.strong_divergence
        else (
            "MILD_DIVERGENCE"
            if rising and divergence >= config.mild_divergence
            else (
                "BROAD_STRENGTH"
                if positive >= config.broad_positive_ratio and divergence < config.mild_divergence
                else "NORMAL"
            )
        )
    )
    velocity = metrics.get("rotation_velocity_3d")
    rotation_state = (
        None
        if velocity is None
        else (
            "EXTREME"
            if velocity >= config.rotation_extreme
            else (
                "FAST"
                if velocity >= config.rotation_fast
                else "NORMAL" if velocity >= config.rotation_normal else "STABLE"
            )
        )
    )
    return {"breadth": breadth_state, "rotation": rotation_state}
