"""Point-in-time consecutive absolute-trend duration for ETF Rotation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, ETFRotationConfig  # pragma: allowlist secret
from finance_analysis.etf_rotation.eligibility import is_absolute_trend_eligible  # pragma: allowlist secret
from finance_analysis.etf_rotation.features import MINIMUM_HISTORY_BARS, calculate_features  # pragma: allowlist secret
from finance_analysis.etf_rotation.models import DailyBar  # pragma: allowlist secret

DURATION_HISTORY_BARS = DEFAULT_CONFIG.history_limit_max
DURATION_CALENDAR_LOOKBACK_DAYS = 548


def count_trend_duration_days(
    bars: Sequence[DailyBar],
    *,
    as_of: date,
    config: ETFRotationConfig = DEFAULT_CONFIG,
) -> int:
    """Count consecutive trading days, ending at ``as_of``, where absolute trend holds.

    Validity reuses ``is_absolute_trend_eligible`` on point-in-time features.  Bars
    after ``as_of`` are ignored.  If ``as_of`` itself is missing or ineligible the
    result is 0; a later eligible day restarts at 1.

    Each session only needs the existing feature warmup (about 21 bars).  Strategy
    ranking still uses its own short window; this lookback is duration-only.
    """
    ordered = [item for item in sorted(bars, key=lambda bar: bar.trade_date) if item.trade_date <= as_of]
    if len(ordered) > DURATION_HISTORY_BARS:
        ordered = ordered[-DURATION_HISTORY_BARS:]
    if not ordered or ordered[-1].trade_date != as_of:
        return 0
    duration = 0
    for end in range(len(ordered), 0, -1):
        start = max(0, end - MINIMUM_HISTORY_BARS)
        window = ordered[start:end]
        if len(window) < MINIMUM_HISTORY_BARS:
            break
        features = calculate_features(window, config)
        if features is None or not is_absolute_trend_eligible(features.to_dict(), config):
            break
        duration += 1
    return duration


__all__ = [
    "DURATION_CALENDAR_LOOKBACK_DAYS",
    "DURATION_HISTORY_BARS",
    "count_trend_duration_days",
]
