# -*- coding: utf-8 -*-
"""Domain models for the A-share intraday analysis task."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional


@dataclass
class AShareCandidate:
    """A symbol selected for the minute-bar / rule stage of the pipeline."""

    code: str
    name: str
    board: str
    origin: str  # watchlist | market_rule | sector_leader
    reason: str = ""
    priority: int = 0
    snapshot: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "board": self.board,
            "origin": self.origin,
            "reason": self.reason,
            "priority": self.priority,
        }


@dataclass
class AShareMarketSnapshot:
    """Market-wide context computed once per run."""

    trading_date: date
    snapshot_time: datetime
    market_phase: str
    indices: Dict[str, Any] = field(default_factory=dict)
    market_stats: Dict[str, Any] = field(default_factory=dict)
    sector_leaders: List[Dict[str, Any]] = field(default_factory=list)
    sector_laggers: List[Dict[str, Any]] = field(default_factory=list)
    market_regime: str = "unknown"
    sentiment_score: Optional[float] = None
    warnings: List[str] = field(default_factory=list)

    def to_context_dict(self) -> Dict[str, Any]:
        return {
            "trading_date": self.trading_date.isoformat(),
            "snapshot_time": self.snapshot_time.isoformat(),
            "market_phase": self.market_phase,
            "market_regime": self.market_regime,
            "sentiment_score": self.sentiment_score,
            "indices": self.indices,
            "market_stats": self.market_stats,
            "sector_leaders": self.sector_leaders[:5],
            "sector_laggers": self.sector_laggers[:5],
            "warnings": self.warnings[:20],
        }


@dataclass
class AShareSignalResult:
    """Outcome of analysing one rule-based candidate with the LLM."""

    code: str
    name: str
    signal_type: str
    board: str
    need_notification: bool
    final_decision: str
    metrics: Dict[str, Any]
    llm_result: Dict[str, Any]
    notification_sent: bool = False
    calendar_id: Optional[int] = None
    fallback_used: bool = False
    severity: str = "info"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "signal_type": self.signal_type,
            "board": self.board,
            "need_notification": self.need_notification,
            "final_decision": self.final_decision,
            "notification_sent": self.notification_sent,
            "calendar_id": self.calendar_id,
            "fallback_used": self.fallback_used,
            "severity": self.severity,
            "summary": str(self.llm_result.get("summary", "") or "")[:300],
        }


@dataclass
class AShareIntradayTaskSummary:
    """Aggregate, JSON-serializable result of one scheduled run."""

    trading_date: date
    snapshot_time: datetime
    market_phase: str
    market_open: bool
    market_regime: str = "unknown"

    total_market_symbols: int = 0
    watchlist_symbols: int = 0
    snapshot_candidate_count: int = 0
    minute_candidate_count: int = 0
    rule_candidate_count: int = 0
    llm_candidate_count: int = 0
    notification_count: int = 0

    up_count: int = 0
    down_count: int = 0
    limit_up_count: int = 0
    limit_down_count: int = 0
    opened_limit_up_count: int = 0

    signal_results: List[AShareSignalResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    calendar_id: Optional[int] = None
    timings: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trading_date": self.trading_date.isoformat(),
            "snapshot_time": self.snapshot_time.isoformat(),
            "market_phase": self.market_phase,
            "market_open": self.market_open,
            "market_regime": self.market_regime,
            "total_market_symbols": self.total_market_symbols,
            "watchlist_symbols": self.watchlist_symbols,
            "snapshot_candidate_count": self.snapshot_candidate_count,
            "minute_candidate_count": self.minute_candidate_count,
            "rule_candidate_count": self.rule_candidate_count,
            "llm_candidate_count": self.llm_candidate_count,
            "notification_count": self.notification_count,
            "up_count": self.up_count,
            "down_count": self.down_count,
            "limit_up_count": self.limit_up_count,
            "limit_down_count": self.limit_down_count,
            "opened_limit_up_count": self.opened_limit_up_count,
            "signal_results": [item.to_dict() for item in self.signal_results],
            "errors": self.errors[:50],
            "warnings": self.warnings[:50],
            "calendar_id": self.calendar_id,
            "timings": self.timings,
        }
