"""Public contract for the fixed US intraday underlying screen."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class WindowScore(BaseModel):
    minutes: Literal[5, 15, 30, 60]
    data_status: Literal["ready", "warming", "gap"]
    available_bars: int | None = None
    missing_bars: int | None = None
    score: float | None = None
    direction: Literal[-1, 0, 1] | None = None
    return_pct: float | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    stability: float | None = None
    efficiency: float | None = None
    strength: float | None = None
    disturbance: float | None = None
    normalized_move: float | None = None
    adverse_move: float | None = None
    adverse_duration: float | None = None
    movement_gate: float | None = None
    concentration: float | None = None
    stalled_impulse: bool = False
    reasons: list[str] = Field(default_factory=list)


class StructurePivot(BaseModel):
    kind: Literal["high", "low"]
    at: datetime
    confirmed_at: datetime
    price: float


class StructureBox(BaseModel):
    upper: float
    lower: float
    start_at: datetime
    end_at: datetime
    atr: float


class AnalysisCoverage(BaseModel):
    required_minutes: int = 15
    recent_available_bars: int = 0
    recent_missing_bars: int = 0
    filled_bars: int = 0
    filled_minutes: list[datetime] = Field(default_factory=list)


class IntradayStructure(AnalysisCoverage):
    kind: Literal["uptrend", "downtrend", "range", "breakout_up", "breakout_down", "failed_up",
                  "failed_down", "rebound", "pullback", "unclear"]
    phase: Literal[
        "waiting", "forming", "confirmed", "retest", "failed", "continuing", "pullback", "pausing", "inside", "warming"
    ]
    background: Literal["bullish", "bearish", "neutral"]
    since: datetime  # Breakout phase occurrence (candle close), stable within the event phase.
    confirmed_at: datetime | None = None  # First confirmation of this breakout attempt.
    as_of: datetime
    oversold: bool
    reference: bool
    available_bars: int
    missing_bars: int
    box: StructureBox | None
    pivots: list[StructurePivot]
    reasons: list[str]


class OpportunityBranch(BaseModel):
    kind: Literal["box_breakout", "box_retest", "trend_recovery", "trend_continuation"]
    process_id: str | None = None
    rule_version: str | None = None
    confirmation_method: Literal["two_closes", "strong_break"] | None = None
    confirmation_available_at: datetime | None = None
    confirmation_run_available_at: datetime | None = None
    execution_evidence_at: datetime | None = None
    triggered_at: datetime | None = None
    structure_start: datetime | None = None
    structure_end: datetime | None = None
    structure_high: float | None = None
    structure_low: float | None = None
    atr_source: str | None = None
    atr_samples: int | None = None
    entry_low: float | None = None
    entry_high: float | None = None
    max_risk_atr: float | None = None
    superseded_by: str | None = None
    breakout_rejection: str | None = None
    direction: Literal["bullish", "bearish"]
    status: Literal["forming", "confirmed", "extended", "invalidated", "expired"]
    structure_id: str
    trigger: float
    invalidation: float
    atr: float
    formation_start: datetime
    started_at: datetime
    confirmed_at: datetime | None
    expires_at: datetime
    quality_score: float | None
    distance_atr: float | None
    risk_atr: float | None
    components: dict[str, float]
    reasons: list[str]


class IntradayOpportunities(AnalysisCoverage):
    version: str
    primary: OpportunityBranch | None
    branches: list[OpportunityBranch]
    reference: bool
    missing_bars: int
    as_of: datetime
    reasons: list[str]


class TrendResult(BaseModel):
    opportunities: IntradayOpportunities | None = None
    structure: IntradayStructure | None = None
    version: str
    symbol: str
    trading_date: date
    as_of: datetime
    observed_at: datetime
    windows: list[WindowScore]
    score: float | None
    direction: Literal["bullish", "bearish", "neutral", "conflict"] | None
    state: Literal["continuing", "pullback", "extended", "conflict", "waiting"] | None
    base_score: float | None
    alignment: float | None
    extension_atr: float | None
    explanation: str


class RankedOpportunity(OpportunityBranch):
    opportunity_reason: str
    execution_reason: str


class IntradayOptionRow(BaseModel):
    simulation: dict | None = None
    ranked_opportunity: RankedOpportunity | None = None
    opportunity_eligible: bool = False
    symbol: str
    name: str | None
    last_price: float | None
    change_pct: float | None
    quote_time: datetime | None
    quote_status: Literal["missing", "ready", "delayed", "invalid_time"]
    data_status: Literal["ready", "waiting", "warming", "gap", "delayed", "invalid_time"]
    issues: list[str]
    result: TrendResult | None


class IntradayOptionsResponse(BaseModel):
    simulation: dict | None = None
    trading_date: date
    market_status: Literal["open", "preopen", "closed"]
    generated_at: datetime
    version: str
    items: list[IntradayOptionRow]
