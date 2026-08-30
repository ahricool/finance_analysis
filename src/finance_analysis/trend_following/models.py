"""Value objects used by the trend-following calculation engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping


@dataclass(frozen=True)
class DailyBar:
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float | None = None


@dataclass(frozen=True)
class UniverseMember:
    market: str
    code: str
    name: str

    def to_dict(self) -> dict[str, str]:
        return {"market": self.market, "code": self.code, "name": self.name}


@dataclass(frozen=True)
class StrategyDecision:
    state: str
    action: str
    entry_price: float | None
    last_add_price: float | None
    units: int
    highest_close: float | None
    initial_stop: float | None
    trailing_stop: float | None
    next_add_price: float | None
    exit_level: float | None
    opened_at: date | None
    suggested_initial_weight: float | None
    suggested_max_weight: float | None
    reasons: list[str]
    signal_date: date | None = None
    signal_price: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


Snapshot = Mapping[str, Any]

__all__ = ["DailyBar", "Snapshot", "StrategyDecision", "UniverseMember"]
