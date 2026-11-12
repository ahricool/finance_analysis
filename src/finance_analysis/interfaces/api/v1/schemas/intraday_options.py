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


class IntradayStructure(BaseModel):
    kind: Literal["uptrend", "downtrend", "range", "breakout_up", "breakout_down", "failed_up",
                  "failed_down", "rebound", "pullback", "unclear"]
    phase: Literal["waiting", "forming", "confirmed", "retest", "failed", "continuing", "pullback", "inside", "warming"]
    background: Literal["bullish", "bearish", "neutral"]
    since: datetime
    as_of: datetime
    oversold: bool
    reference: bool
    available_bars: int
    missing_bars: int
    box: StructureBox | None
    pivots: list[StructurePivot]
    reasons: list[str]


class TrendResult(BaseModel):
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


class IntradayOptionRow(BaseModel):
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
    trading_date: date
    market_status: Literal["open", "preopen", "closed"]
    generated_at: datetime
    version: str
    items: list[IntradayOptionRow]
