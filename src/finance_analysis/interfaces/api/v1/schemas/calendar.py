from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_serializer, field_validator

from finance_analysis.core.time import ensure_aware_utc, utc_isoformat


class CalendarEntryCreate(BaseModel):
    time: datetime
    title: str = Field(..., min_length=1, max_length=120)
    content: Optional[str] = None
    type: Optional[str] = Field(None, max_length=32)

    @field_validator("time")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        try:
            return ensure_aware_utc(value)
        except ValueError as exc:
            raise ValueError("time must include timezone information, e.g. 2026-06-10T01:30:00Z") from exc


class CalendarEntryUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=120)
    content: Optional[str] = None
    type: Optional[str] = Field(None, max_length=32)


class CalendarEntryResponse(BaseModel):
    id: int
    time: datetime
    title: str
    content: Optional[str]
    type: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("time", "created_at", "updated_at")
    def serialize_datetime(self, value: datetime) -> str:
        return utc_isoformat(value) or ""


class CalendarEntryListResponse(BaseModel):
    date: str
    items: List[CalendarEntryResponse]
    total: int
