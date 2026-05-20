from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class CalendarSignalCreate(BaseModel):
    signal_date: date
    title: str = Field(..., min_length=1, max_length=120)
    content: Optional[str] = None
    signal_type: Optional[str] = Field(None, max_length=32)


class CalendarSignalUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=120)
    content: Optional[str] = None
    signal_type: Optional[str] = Field(None, max_length=32)


class CalendarSignalResponse(BaseModel):
    id: int
    signal_date: date
    title: str
    content: Optional[str]
    signal_type: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CalendarSignalListResponse(BaseModel):
    date: date
    items: List[CalendarSignalResponse]
    total: int
