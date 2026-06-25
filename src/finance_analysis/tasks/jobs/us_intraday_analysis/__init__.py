# -*- coding: utf-8 -*-
"""US intraday anomaly detection task package.

Public API is re-exported here so callers can keep importing from the package
root regardless of the internal module layout.
"""

from __future__ import annotations

from .bars import aggregate_bars, normalize_bars
from .config import (
    MARKET_ETFS,
    US_EASTERN,
)
from .llm import build_intraday_llm_prompt, parse_llm_json_response
from .market_calendar import get_us_trading_date, is_us_market_open
from .data_source import filter_current_trading_day_bars
from .metrics import compute_intraday_metrics, cumulative_vwap_series
from .models import IntradaySignalResult, IntradayTaskSummary
from .rules import (
    DEFAULT_INTRADAY_SIGNAL_RULES,
    SignalRule,
    evaluate_signal_candidates,
)
from .service import USIntradayAnalysisService

__all__ = [
    "DEFAULT_INTRADAY_SIGNAL_RULES",
    "SignalRule",
    "MARKET_ETFS",
    "US_EASTERN",
    "USIntradayAnalysisService",
    "IntradaySignalResult",
    "IntradayTaskSummary",
    "aggregate_bars",
    "normalize_bars",
    "filter_current_trading_day_bars",
    "build_intraday_llm_prompt",
    "parse_llm_json_response",
    "get_us_trading_date",
    "is_us_market_open",
    "compute_intraday_metrics",
    "cumulative_vwap_series",
    "evaluate_signal_candidates",
]
