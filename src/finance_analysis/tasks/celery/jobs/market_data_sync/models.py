"""Value objects for unified daily market-data synchronization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from finance_analysis.integrations.market_data.history import AdjustmentData


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
class RoutedAdjustment:
    provider: str | None
    data: AdjustmentData | None
    fallback_reasons: list[str] = field(default_factory=list)


@dataclass
class DailyResult:
    status: Literal["success", "partial", "failed"]
    inserted_rows: int = 0
    updated_rows: int = 0
    skipped_lower_priority_rows: int = 0
    providers: list[str] = field(default_factory=list)
    missing_amount: bool = False
    vwap_qualities: set[str] = field(default_factory=set)
    deleted_rows: int = 0
    reason: str = ""
    fallback_reasons: list[str] = field(default_factory=list)


@dataclass
class AdjustmentResult:
    status: Literal["success", "failed", "skipped"]
    changed: bool = False
    corporate_action_rows: int = 0
    adjustment_factor_rows: int = 0
    deleted_rows: int = 0
    provider: str | None = None
    reason: str = ""
    fallback_reasons: list[str] = field(default_factory=list)


@dataclass
class SymbolResult:
    code: str
    daily: DailyResult
    adjustment: AdjustmentResult


__all__ = [
    "AdjustmentResult",
    "DailyResult",
    "ProviderBars",
    "RoutedAdjustment",
    "RoutedBars",
    "SymbolResult",
]
