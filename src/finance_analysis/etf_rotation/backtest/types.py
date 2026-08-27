"""Transport types for the A-share ETF rotation backtest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class OhlcvBar:
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float | None = None
    suspended: bool = False


@dataclass(frozen=True)
class RotationTrade:
    trade_date: date
    side: str
    code: str
    price: float
    shares: float
    cash_after: float
    signal_date: date
    entry_rank: int | None


@dataclass(frozen=True)
class EquityPoint:
    trade_date: date
    cash: float
    position: str | None
    position_value: float
    total_equity: float


@dataclass(frozen=True)
class RotationBacktestResult:
    start: date
    end: date
    universe_size: int
    ranking_days: int
    execution_days: int
    initial_equity: float
    final_equity: float
    total_return: float
    annualized_return: float
    annualized_return_252: float
    trade_count: int
    trades: tuple[RotationTrade, ...]
    equity: tuple[EquityPoint, ...]
    final_position: str | None


__all__ = ["EquityPoint", "OhlcvBar", "RotationBacktestResult", "RotationTrade"]
