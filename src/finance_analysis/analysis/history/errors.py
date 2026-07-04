"""Errors raised when database-only historical consumers lack required bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence


@dataclass(frozen=True)
class HistoricalMarketDataMissingError(RuntimeError):
    market: str
    code: str
    interval: str
    required_start: date
    required_end: date
    latest_available: Optional[date]
    missing_dates: Sequence[date] = ()
    missing_count: int = 0

    def __str__(self) -> str:
        return (
            f"Historical market data missing: market={self.market} code={self.code} interval={self.interval} "
            f"required_start={self.required_start} required_end={self.required_end} "
            f"latest_available={self.latest_available} missing_count={self.missing_count or len(self.missing_dates)}"
        )
