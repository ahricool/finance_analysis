# -*- coding: utf-8 -*-
"""Shared constants and default rule thresholds for the US intraday task."""

from __future__ import annotations

from typing import Dict
from zoneinfo import ZoneInfo

US_EASTERN = ZoneInfo("America/New_York")

# Number of candidate signals bundled into a single LLM request. Batching avoids
# one LLM call per stock and amortizes latency/cost across the watch list.
LLM_BATCH_SIZE = 10

# Market / sector ETFs used as relative-strength benchmarks. QQQ is treated as
# the broad-market benchmark; the rest are sector references.
MARKET_ETFS = {
    "QQQ": "纳斯达克100指数ETF，作为大盘基准。",
    "XLK": "科技精选板块ETF，代表美国大型科技股。",
    "SOXX": "半导体ETF，追踪美国主要半导体公司。",
    "IGV": "软件行业ETF，作为软件行业基准。",
    "SKYY": "云计算ETF，聚焦美国云计算企业。",
    "UFO": "太空与卫星ETF，覆盖航天及相关领域。",
    "BOTZ": "机器人与人工智能ETF，聚焦机器人及AI行业。",
}

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
