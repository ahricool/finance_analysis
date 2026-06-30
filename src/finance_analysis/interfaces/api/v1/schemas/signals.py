"""Schemas for read-only signal evaluation APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_serializer

from finance_analysis.core.time import utc_isoformat

SignalDirection = Literal["bullish", "bearish", "sideways", "neutral"]


class SignalEvaluationItem(BaseModel):
    status: Optional[str] = None
    reason: Optional[str] = None
    price: Optional[float] = None
    return_pct: Optional[float] = None
    max_return_pct: Optional[float] = None
    min_return_pct: Optional[float] = None
    evaluated_at: Optional[str] = None


class SignalResponse(BaseModel):
    id: int
    market: str
    code: str
    name: Optional[str] = None
    signal_type: Optional[str] = None
    signal_version: str
    direction: SignalDirection
    signal_at: datetime
    signal_price: float = Field(validation_alias="price")
    evaluation: Dict[str, SignalEvaluationItem] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("signal_at", "created_at", "updated_at")
    def serialize_datetime(self, value: datetime) -> str:
        return utc_isoformat(value) or ""


class SignalListResponse(BaseModel):
    items: List[SignalResponse]
    total: int
    page: int
    page_size: int


__all__ = [
    "SignalDirection",
    "SignalEvaluationItem",
    "SignalListResponse",
    "SignalResponse",
]
