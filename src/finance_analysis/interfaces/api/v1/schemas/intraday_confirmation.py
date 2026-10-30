"""Read-only snapshot contract. A null metric explicitly means unavailable."""

from datetime import date, datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

Market = Literal["CN", "US"]
State = Literal["WAIT", "CONFIRMED", "FAILED"]
Source = Literal["confluence", "trend", "etf", "quant"]


class Reason(BaseModel):
    code: str
    text: str


class Confirmation(BaseModel):
    code: str
    name: str
    candidate_sources: list[Source] = Field(default_factory=list)
    source_evidence: list[dict[str, Any]] = Field(default_factory=list)
    instrument_type: str | None = None
    current_status: str = "LEGACY"
    data_status: str | None = None
    conditions: dict[str, bool | None] = Field(default_factory=dict)
    proposed_state: State | None = None
    candidate_source: Source
    candidate_trade_date: date
    candidate_reason: list[str]
    source_generated_at: datetime
    state: State
    confirmation_score: float | None
    available_score_weight: float = 0
    chase_risk: Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
    reasons: list[Reason]
    state_reasons: list[Reason] = Field(default_factory=list)
    metrics: dict[str, Any]
    trend: dict[str, Any]
    score_breakdown: dict[str, float | None] = Field(default_factory=dict)
    first_confirmed_at: datetime | None = None
    first_confirmed_price: float | None = None
    first_confirmed_quote_time: datetime | None = None
    return_3d: float | None = None
    return_5d: float | None = None
    return_10d: float | None = None
    failed_at: datetime | None = None
    max_confirmation_score: float = 0
    current_price_recovered: bool = False
    generated_at: datetime | None = None


class Snapshot(BaseModel):
    market: Market
    trade_date: date
    candidate_trade_date: date | None = None
    frozen_at: datetime | None = None
    generated_at: datetime | None = None
    status: str
    warnings: list[str]
    items: list[Confirmation]
    summary: dict[str, int]
    rules_note: str
    rule_version: str = "intraday_v1"


class RunRequest(BaseModel):
    market: Market = "CN"


class AvailableDates(BaseModel):
    dates: list[date]
