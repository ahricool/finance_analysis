"""Trend Following API contracts."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class TrendFollowingRunRequest(BaseModel):
    market: Literal["CN", "US"] = "CN"
    trade_date: date | None = None


class TrendFollowingPositionResponse(BaseModel):
    code: str
    name: str
    state: Literal["ENTRY", "PYRAMIDING", "HOLDING", "WEAKENING", "REDUCE"]
    action: Literal[
        "WATCH",
        "PENDING_ENTRY",
        "PENDING_ADD",
        "PENDING_REDUCE",
        "PENDING_EXIT",
        "ENTRY",
        "ADD",
        "HOLD",
        "STOP_ADD",
        "REDUCE",
        "EXIT",
        "EXPOSURE_BLOCKED",
    ]
    pending_action: Literal["ENTRY", "ADD", "REDUCE", "EXIT"] | None
    units: int
    unit_weight: float
    position_weight: float
    max_weight: float
    entry_price: float | None
    reference_price: float
    opened_at: date | None
    initial_stop: float | None
    trailing_stop: float | None
    next_add_price: float | None
    exit_level: float | None
    alpha_score: float


class TrendFollowingPortfolioResponse(BaseModel):
    market: Literal["CN", "US"]
    trade_date: date
    market_regime: Literal["RISK_ON", "NEUTRAL", "RISK_OFF"]
    max_exposure: float
    current_exposure: float
    remaining_exposure: float
    position_count: int
    positions: list[TrendFollowingPositionResponse]


class TrendBreadthPoint(BaseModel):
    trade_date: date
    rankable_count: int | None
    trend_breadth: float | None
    deterioration_breadth: float | None
    participation: float | None
    inactive: float | None
    emerging: float | None
    healthy: float | None
    deteriorating: float | None
    state_counts: dict[str, int]
    coverage: float | None
    warning: str | None
    is_preview: bool


class TrendBreadthResponse(BaseModel):
    market: Literal["CN", "US"]
    dates: list[date]
    official_count: int
    preview_date: date | None
    preview_time: datetime | None
    generated_at: datetime | None
    points: list[TrendBreadthPoint]
    warnings: list[str]


class TrendTransition(BaseModel):
    code: str
    name: str
    previous_state: str
    current_state: str
    previous_date: date
    trade_date: date
    previous_rank: int
    current_rank: int
    rank_delta: int
    alpha_score: float | None
    fragility_score: float | None
    direction: Literal["strengthening", "deteriorating"]
    priority: int
    is_preview: bool


class TrendTransitionsResponse(BaseModel):
    market: Literal["CN", "US"]
    days: int
    official_count: int
    preview_date: date | None
    warnings: list[str]
    items: list[TrendTransition]
