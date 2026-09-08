"""SDK-free result contract for calendar adapters."""

from dataclasses import dataclass, field


@dataclass
class CalendarFetchResult:
    unsupported_reason: str | None = None
    events: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    pages_succeeded: int = 0
    fetched: int = 0
    skipped: int = 0
