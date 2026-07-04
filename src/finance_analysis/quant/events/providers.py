"""Provider contract; implementations must report unavailability explicitly."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class RawMarketEvent:
    code: str | None
    event_type: str
    published_at: datetime
    direction: str
    importance: float
    confidence: float
    source: str
    source_event_id: str
    title: str
    payload: dict


class EventProvider(Protocol):
    provider_key: str

    def is_available(self) -> bool: ...

    def fetch_events(self, start_time: datetime, end_time: datetime, symbols: list[str]) -> list[RawMarketEvent]: ...
