"""Explicit authenticated read contract for immutable daily research decisions."""

from datetime import date, datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator
from finance_analysis.signal_center.prompt import Decision
from finance_analysis.signal_center.decision import Decision as MultiDecision, Evidence, ExternalSource

Market = Literal["CN", "US"]


class ReturnHorizon(BaseModel):
    days: Literal[1, 3, 5, 10]
    target_date: date
    status: Literal["pending", "missing", "available"]
    value: float | None


class SignalEvaluation(BaseModel):
    method: Literal["next_session_open_v1"]
    status: Literal["not_applicable", "pending", "partial", "complete", "unavailable"]
    reason: str | None = None
    entry_date: date | None = None
    entry_price: float | None = None
    as_of: date | None = None
    observed_sessions: int = 0
    missing_dates: list[date] = []
    horizons: list[ReturnHorizon] = []
    mfe: float | None = None
    mae: float | None = None
    max_drawdown_close: float | None = None
    evaluated_at: datetime


class SignalPick(BaseModel):
    symbol: str
    name: str | None = None
    instrument_type: str = "STOCK"
    confidence: Literal["low", "medium", "high"] | None = None
    thesis: str = ""
    positive_signals: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidations: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    external_sources: list[ExternalSource] = Field(default_factory=list)
    evaluation: SignalEvaluation | None = None


class SignalSummary(BaseModel):
    market: Market
    signal_date: date
    status: Literal["pending", "completed", "failed", "skipped"]
    selected_symbol: str | None = None
    selected_name: str | None = None
    decision: Literal["BUY", "NO_TRADE"] | None = None
    confidence: Literal["low", "medium", "high"] | None = None
    created_at: datetime
    completed_at: datetime | None = None
    evaluation: SignalEvaluation
    recommendations: list[SignalPick] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def name_from_snapshot(cls, data):
        if not isinstance(data, dict):
            return data
        symbol = data.get("selected_symbol")
        candidates = (data.get("candidate_snapshot") or {}).get("candidates", [])
        name = next((c.get("name") for c in candidates if symbol and c.get("symbol") == symbol), None)
        return {**data, "selected_name": name}


class SignalDetail(SignalSummary):
    analysis: Decision | MultiDecision | None = None
    search_evidence: dict[str, Any] | None = None
    candidate_snapshot: dict[str, Any]
    model: str | None = None
    backend: str | None = None
    prompt_version: str
    screening: list[dict[str, Any]] | None = None
    error: str | None = None


class DailySignals(BaseModel):
    items: list[SignalDetail]
    requested_dates: dict[Market, date]
