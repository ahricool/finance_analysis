"""Small value objects for synchronization orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal


SyncMode = Literal["bootstrap", "repair"]


@dataclass(frozen=True)
class DailyWindow:
    mode: SyncMode
    start_date: date
    end_date: date
    trading_days: tuple[date, ...]


@dataclass(frozen=True)
class MinuteWindow:
    mode: SyncMode
    trading_days: tuple[date, ...]


@dataclass
class ProviderBars:
    provider: str
    priority: int
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RoutedBars:
    batches: list[ProviderBars]
    missing: list[Any]
    providers_used: list[str]
    requested_range: str
    fallback_reasons: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing


@dataclass
class DataTypeResult:
    status: Literal["success", "partial", "failed", "skipped"]
    mode: SyncMode
    inserted_rows: int = 0
    updated_rows: int = 0
    skipped_lower_priority_rows: int = 0
    providers: list[str] = field(default_factory=list)
    requested_range: str = ""
    actual_range: str = ""
    reason: str = ""
    fallback_reasons: list[str] = field(default_factory=list)


@dataclass
class SymbolResult:
    code: str
    daily: DataTypeResult | None = None
    minute: DataTypeResult | None = None
