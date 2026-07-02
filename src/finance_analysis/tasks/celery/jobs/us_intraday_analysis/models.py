# -*- coding: utf-8 -*-
"""Domain models for the US intraday anomaly detection task."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

FILTER_FAILURE_KEYS = (
    "insufficient_bars",
    "stale_bars",
    "missing_quote",
    "missing_qqq_context",
    "change_5m",
    "change_15m",
    "relative_to_qqq",
    "volume_ratio",
    "vwap_position",
    "near_high",
    "early_relative_strength",
)


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

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "symbol": self.symbol,
            "signal_type": self.signal_type,
            "need_notification": bool(self.need_notification),
            "llm_result": _jsonable(self.llm_result),
            "metrics": _jsonable(self.metrics),
            "calendar_id": self.calendar_id,
            "notification_sent": bool(self.notification_sent),
        }


@dataclass
class IntradayTaskSummary:
    """Aggregate result of one scheduled run across all watched symbols."""

    market_open: bool
    total_symbols: int = 0
    processed_symbols: int = 0
    skipped_symbols: int = 0
    stale_symbols: int = 0
    candidate_count: int = 0
    llm_candidate_count: int = 0
    notification_count: int = 0
    notification_suppressed_count: int = 0
    rule_match_counts: Dict[str, int] = field(default_factory=dict)
    filter_failure_counts: Dict[str, int] = field(default_factory=dict)
    timings: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    status: str = "completed"
    degraded: bool = False
    signal_results: List[IntradaySignalResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for key in FILTER_FAILURE_KEYS:
            self.filter_failure_counts.setdefault(key, 0)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable summary for task-center storage."""
        return {
            "market_open": bool(self.market_open),
            "total_symbols": int(self.total_symbols),
            "processed_symbols": int(self.processed_symbols),
            "skipped_symbols": int(self.skipped_symbols),
            "stale_symbols": int(self.stale_symbols),
            "candidate_count": int(self.candidate_count),
            "llm_candidate_count": int(self.llm_candidate_count),
            "notification_count": int(self.notification_count),
            "notification_suppressed_count": int(self.notification_suppressed_count),
            "rule_match_counts": dict(self.rule_match_counts),
            "filter_failure_counts": dict(self.filter_failure_counts),
            "timings": _jsonable(self.timings),
            "warnings": list(self.warnings),
            "status": self.status,
            "degraded": bool(self.degraded),
            "signal_results": [item.to_dict() for item in self.signal_results],
            "errors": list(self.errors),
        }


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
