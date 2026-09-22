"""Explicit authenticated read contract for immutable daily research decisions."""

from datetime import date, datetime
from typing import Any, Literal
from pydantic import BaseModel
from finance_analysis.signal_center.prompt import Decision

Market = Literal["CN", "US"]


class SignalSummary(BaseModel):
    market: Market
    signal_date: date
    status: Literal["pending", "completed", "failed", "skipped"]
    selected_symbol: str | None = None
    decision: Literal["BUY", "NO_TRADE"] | None = None
    confidence: Literal["low", "medium", "high"] | None = None
    created_at: datetime
    completed_at: datetime | None = None


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
