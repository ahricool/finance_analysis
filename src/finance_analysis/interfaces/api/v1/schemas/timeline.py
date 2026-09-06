from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from finance_analysis.timeline.dto import Actionability, Importance


class NoteInput(BaseModel):
    event_time: datetime
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=100000)
    market: Literal["CN", "US"] | None = None
    importance: Importance = "normal"
    actionability: Actionability = "none"
    symbol: str | None = Field(default=None, max_length=32)
    related_symbols: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("event_time")
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None:
            raise ValueError("event_time must include a timezone offset")
        return value

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value):
        if not value.strip():
            raise ValueError("title must not be blank")
        return value.strip()
