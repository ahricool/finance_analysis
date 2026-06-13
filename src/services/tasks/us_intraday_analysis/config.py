# -*- coding: utf-8 -*-
"""Shared constants and default rule thresholds for the US intraday task."""

from __future__ import annotations

from typing import Dict
from zoneinfo import ZoneInfo

US_EASTERN = ZoneInfo("America/New_York")

REDIS_TTL_SECONDS = 7 * 24 * 60 * 60
SIGNAL_DEDUP_TTL_SECONDS = 30 * 60

# Market / sector ETFs used as relative-strength benchmarks. QQQ is treated as
# the broad-market benchmark; the rest are sector references.
MARKET_ETFS = ("QQQ", "SOXX", "UFO")

DEFAULT_INTRADAY_SIGNAL_RULES: Dict[str, Dict[str, float]] = {
    "relative_strength_breakout": {
        "change_5m_min": 0.8,
        "change_15m_min": 1.5,
        "relative_to_qqq_15m_min": 0.8,
        "volume_ratio_5m_min": 2.0,
        "near_high_pct": 0.25,
    },
    "weak_to_strong_reversal": {
        "early_relative_to_qqq_max": -0.3,
        "relative_to_qqq_15m_min": 0.3,
        "change_15m_min": 1.0,
        "volume_ratio_5m_min": 1.8,
    },
    "relative_strength_failure": {
        "early_relative_to_qqq_min": 0.5,
        "relative_to_qqq_15m_max": -0.3,
        "change_5m_max": -0.8,
        "volume_ratio_5m_min": 2.0,
    },
}
