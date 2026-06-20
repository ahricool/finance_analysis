# -*- coding: utf-8 -*-
"""Shared constants for the US intraday task.

Signal rules now live in :mod:`.rules` as callables; see
``DEFAULT_INTRADAY_SIGNAL_RULES`` there.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

US_EASTERN = ZoneInfo("America/New_York")

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
