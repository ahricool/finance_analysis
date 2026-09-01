"""Value objects for unified daily market-data synchronization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SyncMode = Literal["incremental", "full"]
SYNC_MODES: tuple[SyncMode, ...] = ("incremental", "full")


def normalize_sync_mode(value: str | None) -> SyncMode:
    normalized = str(value or "incremental").strip().lower()
    if normalized not in SYNC_MODES:
        raise ValueError(f"Unsupported sync_mode={value!r}; expected one of {', '.join(SYNC_MODES)}")
    return normalized  # type: ignore[return-value]


@dataclass
class DailyResult:
    status: Literal["success", "partial", "failed"]
    inserted_rows: int = 0
    updated_rows: int = 0
    providers: list[str] = field(default_factory=list)
    missing_amount: bool = False
    deleted_rows: int = 0
    automatic_full_refresh: bool = False
    reason: str = ""
    fallback_reasons: list[str] = field(default_factory=list)


@dataclass
class SymbolResult:
    code: str
    daily: DailyResult


__all__ = [
    "DailyResult",
    "SYNC_MODES",
    "SyncMode",
    "SymbolResult",
    "normalize_sync_mode",
]
