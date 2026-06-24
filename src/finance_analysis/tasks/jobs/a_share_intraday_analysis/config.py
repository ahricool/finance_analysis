# -*- coding: utf-8 -*-
"""Shared constants and tunables for the A-share intraday analysis task.

Signal rules live in :mod:`.rules` as callables; price-limit handling lives in
:mod:`.price_limits`. Everything here is deterministic configuration so the
behaviour stays predictable across runs.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

ASIA_SHANGHAI = ZoneInfo("Asia/Shanghai")

# Task / calendar identifiers (kept stable for the task center and history).
A_SHARE_INTRADAY_TASK_TYPE = "scheduled_a_share_intraday"
A_SHARE_INTRADAY_SIGNAL_CALENDAR_TYPE = "a_share_intraday_signal"
A_SHARE_INTRADAY_SUMMARY_CALENDAR_TYPE = "scheduled_a_share_intraday"

# Candidate pool ceilings. Two-stage scanning means only a bounded number of
# symbols ever reach minute-bar fetching or the LLM.
MAX_MARKET_SNAPSHOT_CANDIDATES = 60
MAX_MINUTE_BAR_CANDIDATES = 40
MAX_LLM_CANDIDATES_PER_RUN = 30
LLM_BATCH_SIZE = 8

# Minimum normalized minute bars required before fine-grained rules run.
MIN_BARS_FOR_SYMBOL = 12
MIN_BARS_FOR_BENCHMARK = 8

# Per-symbol / market news retention caps.
MAX_NEWS_PER_SYMBOL = 5
MAX_MARKET_NEWS = 10

# Notification limits per run.
MAX_AGGREGATED_SIGNALS = 8

# A-share index universe. Codes are the canonical 6-digit forms used by the
# providers; ``get_main_indices`` returns prefixed codes we map back below.
A_SHARE_INDICES = {
    "000001": "上证指数",
    "399001": "深证成指",
    "399006": "创业板指",
    "000300": "沪深300",
    "000905": "中证500",
    "000852": "中证1000",
    "000688": "科创50",
    "899050": "北证50",
}

# Map ``get_main_indices`` prefixed codes to the canonical codes above.
INDEX_CODE_ALIASES = {
    "sh000001": "000001",
    "sz399001": "399001",
    "sz399006": "399006",
    "sh000300": "000300",
    "sh000905": "000905",
    "sh000852": "000852",
    "sh000688": "000688",
    "bj899050": "899050",
}

# Benchmark index per board (relative-strength reference).
BOARD_BENCHMARK_INDEX = {
    "main_board": "000300",
    "chinext": "399006",
    "star_market": "000688",
    "bse": "899050",
    "st_or_risk_warning": "000300",
    "new_listing_unbounded": "000300",
    "etf": "000300",
    "unknown": "000001",
}

# External-call timeouts (seconds).
MINUTE_FETCH_TIMEOUT = 20
LLM_TIMEOUT = 90
