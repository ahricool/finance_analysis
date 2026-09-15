"""Trend Following API contracts."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class TrendFollowingRunRequest(BaseModel):
    market: Literal["CN", "US"] = "CN"
    trade_date: date | None = None


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


TrendState = Literal["IDLE", "WATCHING", "CANDIDATE", "TRENDING", "WEAKENING", "BROKEN"]


class TrendTransition(BaseModel):
    code: str
    name: str
    previous_state: TrendState
    current_state: TrendState
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
