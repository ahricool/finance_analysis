"""Explicit authenticated read contract for immutable daily research decisions."""

from datetime import date, datetime
from typing import Any, Literal
from pydantic import BaseModel
from finance_analysis.signal_center.prompt import Decision

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


class SignalSummary(BaseModel):
    market: Market
    signal_date: date
    status: Literal["pending", "completed", "failed", "skipped"]
    selected_symbol: str | None = None
    decision: Literal["BUY", "NO_TRADE"] | None = None
    confidence: Literal["low", "medium", "high"] | None = None
    created_at: datetime
    completed_at: datetime | None = None
    evaluation: SignalEvaluation


class SignalDetail(SignalSummary):
    analysis: Decision | None = None
    candidate_snapshot: dict[str, Any]
    model: str | None = None
    backend: str | None = None
    prompt_version: str
    screening: list[dict[str, Any]] | None = None
    error: str | None = None


class DailySignals(BaseModel):
    items: list[SignalDetail]
    requested_dates: dict[Market, date]
