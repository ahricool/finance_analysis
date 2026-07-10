"""Small JSON-serializable models used by the pre-close review pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Optional


@dataclass
class DataQuality:
    snapshot_time: Optional[datetime] = None
    quote_age_seconds: Optional[int] = None
    fresh_quotes: bool = False
    market_complete: bool = False
    market_rows: int = 0
    index_coverage: int = 0
    indices_complete: bool = False
    sector_coverage: int = 0
    sectors_complete: bool = False
    holding_coverage: int = 0
    holding_total: int = 0
    history_coverage: int = 0
    minute_coverage: int = 0
    news_coverage: int = 0
    news_complete: bool = False
    issues: list[str] = field(default_factory=list)

    @property
    def sufficient_for_active_advice(self) -> bool:
        if not self.fresh_quotes or not self.market_complete or self.market_rows <= 0:
            return False
        if self.holding_total and self.holding_coverage < self.holding_total:
            return False
        return self.indices_complete and self.sectors_complete and self.news_complete

    @property
    def confidence(self) -> str:
        if not self.sufficient_for_active_advice:
            return "low"
        if self.issues or self.history_coverage < max(1, self.holding_total):
            return "medium"
        return "high"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["snapshot_time"] = self.snapshot_time.isoformat() if self.snapshot_time else None
        payload["sufficient_for_active_advice"] = self.sufficient_for_active_advice
        payload["confidence"] = self.confidence
        return payload


@dataclass
class SectorReview:
    name: str
    change_pct: float
    continuity: str
    rationale: str
    pullback_from_high_pct: Optional[float] = None
    prior_appearances: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SecurityReview:
    code: str
    name: str
    change_pct: Optional[float]
    price: Optional[float]
    amount: Optional[float]
    sector: Optional[str]
    relative_to_market_pct: Optional[float]
    relative_to_sector_pct: Optional[float]
    daily_trend: str
    intraday_trend: str
    data_complete: bool
    avg_cost: Optional[float] = None
    unrealized_pct: Optional[float] = None
    source: str = "holding"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreCloseReviewSummary:
    trading_date: date
    started_at: datetime
    finished_at: datetime
    market_state: str
    market_rationale: list[str]
    turnover_state: str
    risk_state: str
    breadth: dict[str, Any]
    indices: list[dict[str, Any]]
    market_trends: list[dict[str, Any]]
    strong_sectors: list[SectorReview]
    holdings: list[SecurityReview]
    candidates: list[SecurityReview]
    news: list[dict[str, Any]]
    decision: dict[str, Any]
    data_quality: DataQuality
    warnings: list[str] = field(default_factory=list)
    calendar_id: Optional[int] = None
    notification_sent: bool = False
    fallback_used: bool = False
    llm_calls: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trading_date": self.trading_date.isoformat(),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "market_state": self.market_state,
            "market_rationale": self.market_rationale[:10],
            "turnover_state": self.turnover_state,
            "risk_state": self.risk_state,
            "breadth": self.breadth,
            "indices": self.indices[:8],
            "market_trends": self.market_trends[:5],
            "strong_sectors": [item.to_dict() for item in self.strong_sectors],
            "holdings": [item.to_dict() for item in self.holdings],
            "candidates": [item.to_dict() for item in self.candidates],
            "news": self.news[:20],
            "decision": self.decision,
            "data_quality": self.data_quality.to_dict(),
            "warnings": self.warnings[:50],
            "calendar_id": self.calendar_id,
            "notification_sent": self.notification_sent,
            "fallback_used": self.fallback_used,
            "llm_calls": self.llm_calls,
        }

    def to_task_result_dict(self) -> dict[str, Any]:
        """Return a bounded result that remains queryable in task history."""
        decision = self.decision
        compact_decision = {
            "market_summary": decision.get("market_summary", {}),
            "sector_views": list(decision.get("sector_views") or [])[:5],
            "risks": list(decision.get("risks") or [])[:6],
            "holdings": list(decision.get("holdings") or [])[:10],
            "candidates": list(decision.get("candidates") or [])[:6],
            "invalidation_conditions": list(decision.get("invalidation_conditions") or [])[:6],
            "confidence": decision.get("confidence"),
            "data_note": decision.get("data_note"),
        }
        return {
            "trading_date": self.trading_date.isoformat(),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "market_state": self.market_state,
            "market_rationale": self.market_rationale[:8],
            "turnover_state": self.turnover_state,
            "risk_state": self.risk_state,
            "breadth": self.breadth,
            "indices": self.indices[:8],
            "market_trends": self.market_trends[:5],
            "strong_sectors": [item.to_dict() for item in self.strong_sectors[:5]],
            "holdings": [item.to_dict() for item in self.holdings[:10]],
            "candidates": [item.to_dict() for item in self.candidates[:6]],
            "news": [
                {
                    "entity_key": item.get("entity_key"),
                    "impact": item.get("impact"),
                    "coverage": item.get("coverage"),
                    "summary": str(item.get("summary") or "")[:160],
                }
                for item in self.news[:12]
            ],
            "decision": compact_decision,
            "data_quality": self.data_quality.to_dict(),
            "warnings": self.warnings[:20],
            "calendar_id": self.calendar_id,
            "notification_sent": self.notification_sent,
            "fallback_used": self.fallback_used,
            "llm_calls": self.llm_calls,
        }
