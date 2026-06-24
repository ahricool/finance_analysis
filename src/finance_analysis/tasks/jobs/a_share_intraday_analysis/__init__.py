# -*- coding: utf-8 -*-
"""A-share intraday anomaly detection task package.

Public API is re-exported here so callers can keep importing from the package
root regardless of the internal module layout.
"""

from __future__ import annotations

from .bars import aggregate_bars, normalize_bars
from .config import ASIA_SHANGHAI
from .llm import (
    AShareIntradayLLMJudge,
    build_batch_prompt,
    candidate_id,
    parse_llm_json_response,
)
from .market_calendar import (
    get_a_share_market_now,
    get_a_share_market_phase,
    is_a_share_intraday_analysis_time,
    is_a_share_trading_day,
    parse_a_share_timestamp,
)
from .metrics import compute_a_share_intraday_metrics
from .models import (
    AShareCandidate,
    AShareIntradayTaskSummary,
    AShareMarketSnapshot,
    AShareSignalResult,
)
from .price_limits import (
    PriceLimitRule,
    classify_a_share_board,
    resolve_price_limit_rule,
)
from .rules import (
    DEFAULT_A_SHARE_INTRADAY_SIGNAL_RULES,
    SignalRule,
    evaluate_signal_candidates,
)
from .service import (
    AShareIntradayAnalysisService,
    compute_market_breadth,
    determine_market_regime,
)

__all__ = [
    "ASIA_SHANGHAI",
    "AShareIntradayAnalysisService",
    "AShareIntradayLLMJudge",
    "AShareIntradayTaskSummary",
    "AShareMarketSnapshot",
    "AShareSignalResult",
    "AShareCandidate",
    "PriceLimitRule",
    "SignalRule",
    "DEFAULT_A_SHARE_INTRADAY_SIGNAL_RULES",
    "aggregate_bars",
    "normalize_bars",
    "build_batch_prompt",
    "candidate_id",
    "parse_llm_json_response",
    "classify_a_share_board",
    "resolve_price_limit_rule",
    "compute_a_share_intraday_metrics",
    "compute_market_breadth",
    "determine_market_regime",
    "evaluate_signal_candidates",
    "get_a_share_market_now",
    "get_a_share_market_phase",
    "is_a_share_intraday_analysis_time",
    "is_a_share_trading_day",
    "parse_a_share_timestamp",
]
