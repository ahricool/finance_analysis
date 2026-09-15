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
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


Snapshot = Mapping[str, Any]

__all__ = ["DailyBar", "Snapshot", "StrategyDecision", "UniverseMember"]
