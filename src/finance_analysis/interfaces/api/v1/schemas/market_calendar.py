from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_serializer, field_validator

from finance_analysis.core.time import ensure_aware_utc, utc_isoformat


class FinanceEventCreate(BaseModel):
    calendar_type: str = Field(..., min_length=1, max_length=32)
    market: str = Field("US", min_length=1, max_length=16)
    symbol: Optional[str] = Field(None, max_length=32)
    counter_name: Optional[str] = Field(None, max_length=128)
    event_type: Optional[str] = Field(None, max_length=64)
    activity_type: Optional[str] = Field(None, max_length=64)
    event_date: date
    event_datetime: Optional[datetime] = None
    date_type: Optional[str] = Field(None, max_length=32)
    financial_market_time: Optional[str] = Field(None, max_length=64)
    title: str = Field(..., min_length=1, max_length=120)
    content: str = ""
    star: Optional[int] = Field(None, ge=0, le=5)
    currency: Optional[str] = Field(None, max_length=16)

    @field_validator("event_datetime")
    @classmethod
    def require_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        try:
            return ensure_aware_utc(value)
        except ValueError as exc:
            raise ValueError("event_datetime must include timezone information") from exc


class FinanceEventResponse(BaseModel):
    id: int
    provider: str
    provider_event_id: Optional[str]
    event_key: str
    calendar_type: str
    market: str
    symbol: Optional[str]
    counter_name: Optional[str]
    event_type: Optional[str]
    activity_type: Optional[str]
    event_date: date
    event_datetime: Optional[datetime]
    date_type: Optional[str]
    financial_market_time: Optional[str]
    title: str
    content: str
    star: Optional[int]
    currency: Optional[str]
    data_kv_json: Optional[str]
    importance_score: Optional[int]
    importance_reason: Optional[str]
    importance_confidence: Optional[float]
    importance_model: Optional[str]
    importance_prompt_version: Optional[str]
    importance_input_hash: Optional[str]
    importance_scored_at: Optional[datetime]
    first_seen_at: datetime
    last_seen_at: datetime
    notified_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("event_date")
    def serialize_date(self, value: date) -> str:
        return value.isoformat()

    @field_serializer(
        "event_datetime",
        "importance_scored_at",
        "first_seen_at",
        "last_seen_at",
        "notified_at",
        "created_at",
        "updated_at",
    )
    def serialize_datetime(self, value: Optional[datetime]) -> Optional[str]:
        return utc_isoformat(value)


class FinanceEventListResponse(BaseModel):
    date: str
    items: List[FinanceEventResponse]
    total: int
