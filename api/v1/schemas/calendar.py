from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class CalendarEntryCreate(BaseModel):
    time: datetime
    title: str = Field(..., min_length=1, max_length=120)
    content: Optional[str] = None
    type: Optional[str] = Field(None, max_length=32)


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


class CalendarEntryListResponse(BaseModel):
    date: str
    items: List[CalendarEntryResponse]
    total: int
