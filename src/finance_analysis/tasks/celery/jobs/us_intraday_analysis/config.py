# -*- coding: utf-8 -*-
"""Shared constants for the US intraday task.

Signal rules now live in :mod:`.rules` as callables; see
``DEFAULT_INTRADAY_SIGNAL_RULES`` there.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

US_EASTERN = ZoneInfo("America/New_York")

# Normal US regular session minute bars: 09:30 through 15:59. Request a small
# buffer beyond 390 minutes so provider gaps do not force a second call.
DEFAULT_INTRADAY_BAR_COUNT = 420

# Stale data guard for scheduled intraday analysis.
STALE_BAR_SECONDS = 3 * 60

# Lock TTLs. The running lock protects overlapping workers; the window lock is
# kept after success so the same schedule window is not processed again.
US_INTRADAY_RUNNING_LOCK_TTL_SECONDS = 14 * 60
US_INTRADAY_WINDOW_LOCK_TTL_SECONDS = 2 * 60 * 60

# Number of candidate signals bundled into a single LLM request. Batching avoids
# one LLM call per stock and amortizes latency/cost across the watch list.
LLM_BATCH_SIZE = 10

# Longbridge news items fetched per symbol for intraday LLM context.
INTRADAY_NEWS_LIMIT = 5

# Broad-market symbol used for macro news context.
MARKET_NEWS_SYMBOL = "QQQ"

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


RELATIVE_STRENGTH_BREAKOUT_RULE = {
    "normal": {
        "change_5m_min": 0.35,
        "change_15m_min": 0.8,
        "relative_to_qqq_15m_min": 0.35,
        "volume_ratio_5m_min": 1.3,
        "near_high_pct": 0.8,
        "min_score": 4.0,
    },
    "strong": {
        "change_5m_min": 0.8,
        "change_15m_min": 1.5,
        "relative_to_qqq_15m_min": 0.8,
        "volume_ratio_5m_min": 2.0,
        "near_high_pct": 0.25,
    },
}

WEAK_TO_STRONG_REVERSAL_RULE = {
    "normal": {
        "early_relative_to_qqq_max": -0.2,
        "relative_to_qqq_15m_min": 0.1,
        "change_15m_min": 0.5,
        "volume_ratio_5m_min": 1.3,
        "min_score": 4.0,
    },
    "strong": {
        "early_relative_to_qqq_max": -0.3,
        "relative_to_qqq_15m_min": 0.3,
        "change_15m_min": 1.0,
        "volume_ratio_5m_min": 1.8,
    },
}

RELATIVE_STRENGTH_FAILURE_RULE = {
    "normal": {
        "early_relative_to_qqq_min": 0.3,
        "relative_to_qqq_15m_max": -0.1,
        "change_5m_max": -0.4,
        "volume_ratio_5m_min": 1.3,
        "min_score": 4.0,
    },
    "strong": {
        "early_relative_to_qqq_min": 0.5,
        "relative_to_qqq_15m_max": -0.3,
        "change_5m_max": -0.8,
        "volume_ratio_5m_min": 2.0,
    },
}
