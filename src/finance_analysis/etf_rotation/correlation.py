"""Point-in-time rolling return correlations for candidate de-duplication."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence

from finance_analysis.etf_rotation.models import DailyBar


def rolling_correlations(
    histories: Mapping[str, Sequence[DailyBar]], window: int = 60
) -> dict[tuple[str, str], float | None]:
    returns: dict[str, dict[object, float]] = {}
    for code, bars in histories.items():
        ordered = sorted(bars, key=lambda bar: bar.trade_date)[-(window + 1):]
        returns[code] = {
            ordered[index].trade_date: ordered[index].close / ordered[index - 1].close - 1.0
            for index in range(1, len(ordered))
            if ordered[index - 1].close > 0
        }
    result: dict[tuple[str, str], float | None] = {}
    codes = sorted(returns)
    for left_index, left in enumerate(codes):
        for right in codes[left_index + 1:]:
            dates = sorted(set(returns[left]) & set(returns[right]))
            key = (left, right)
            if len(dates) < window:
                result[key] = None
                continue
            x = [returns[left][item] for item in dates[-window:]]
            y = [returns[right][item] for item in dates[-window:]]
            std_x, std_y = statistics.stdev(x), statistics.stdev(y)
            if std_x <= 1e-12 or std_y <= 1e-12:
                result[key] = None
                continue
            correlation = statistics.covariance(x, y) / (std_x * std_y)
            result[key] = max(-1.0, min(1.0, correlation)) if math.isfinite(correlation) else None
    return result


__all__ = ["rolling_correlations"]
