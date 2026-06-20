# -*- coding: utf-8 -*-
"""Domain models for the US intraday anomaly detection task."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class IntradaySignalResult:
    """Outcome of analysing a single rule-based candidate with the LLM."""

    symbol: str
    signal_type: str
    need_notification: bool
    llm_result: Dict[str, Any]
    metrics: Dict[str, Any]
    calendar_id: Optional[int] = None
    notification_sent: bool = False


@dataclass
class IntradayTaskSummary:
    """Aggregate result of one scheduled run across all watched symbols."""

    market_open: bool
    total_symbols: int = 0
    processed_symbols: int = 0
    skipped_symbols: int = 0
    candidate_count: int = 0
    signal_results: List[IntradaySignalResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
