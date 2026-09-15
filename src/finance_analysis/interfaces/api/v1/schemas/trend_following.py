"""Trend Following API contracts."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class TrendFollowingRunRequest(BaseModel):
    market: Literal["CN", "US"] = "CN"
    trade_date: date | None = None


class TrendStateHistoryCell(BaseModel):
    rank: int
    state: Literal["IDLE", "WATCHING", "CANDIDATE", "TRENDING", "WEAKENING", "BROKEN"]
    alpha_score: float | None
    trend_score: float | None
    rs_score: float | None
    fragility_score: float | None
    trend_duration_days: int | None


class TrendStateHistoryItem(BaseModel):
    code: str
    name: str
    current_rank: int
    history: list[TrendStateHistoryCell | None]


class TrendStateHistoryResponse(BaseModel):
    market: Literal["CN", "US"]
    anchor_date: date | None
    dates: list[date]
    official_count: int
    preview_date: date | None
    preview_time: datetime | None
    generated_at: datetime | None
    warnings: list[str]
    items: list[TrendStateHistoryItem]


__all__ = [
    "TrendFollowingRunRequest",
    "TrendStateHistoryCell", "TrendStateHistoryItem", "TrendStateHistoryResponse",
]
