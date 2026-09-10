"""Point-in-time consecutive trend-candidate duration for Trend Following."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from finance_analysis.trend_following.features import calculate_features  # pragma: allowlist secret
from finance_analysis.trend_following.models import DailyBar  # pragma: allowlist secret


def count_trend_duration_days(
    bars: Sequence[DailyBar],
    *,
    as_of: date,
    minimum_bars: int = 21,
) -> int:
    """Count consecutive trading days, ending at ``as_of``, where trend_candidate holds.

    Validity reuses ``calculate_features(... )["trend_candidate"]``.  Bars after
    ``as_of`` are ignored.  If ``as_of`` itself is missing or ineligible the result
    is 0; a later eligible day restarts at 1.
    """
    ordered = [item for item in sorted(bars, key=lambda bar: bar.trade_date) if item.trade_date <= as_of]
    if not ordered or ordered[-1].trade_date != as_of:
        return 0
    duration = 0
    for end in range(len(ordered), 0, -1):
        features = calculate_features(ordered[:end], minimum_bars)
        if features is None or not features["trend_candidate"]:
            break
        duration += 1
    return duration


__all__ = ["count_trend_duration_days"]
