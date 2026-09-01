"""Trend Following API write contracts."""

from datetime import date
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


__all__ = [
    "TrendFollowingPortfolioResponse",
    "TrendFollowingPositionResponse",
    "TrendFollowingRunRequest",
]
