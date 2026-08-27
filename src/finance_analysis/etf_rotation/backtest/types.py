"""Transport types for the ETF rotation research backtest."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


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
class StrategySpec:
    strategy_id: str
    name: str
    max_positions: int
    buy_entry_rank: int
    absolute_filter: bool = False
    exit_entry_rank: int | None = None
    exit_momentum_rank: int | None = None
    exit_weak: bool = False
    stop_loss: bool = False
    trailing_stop: bool = False
    risk_off: bool = False
    hysteresis: bool = False
    hysteresis_hold_rank: int = 15
    hysteresis_observe_rank: int = 20
    hysteresis_exit_days: int = 2
    risk_off_threshold: float = 0.30


@dataclass
class OpenPosition:
    code: str
    shares: float
    entry_date: date
    entry_price: float
    signal_date: date
    entry_rank: int | None
    stop_pct: float | None = None
    stop_price: float | None = None
    high_water: float = 0.0
    mae: float = 0.0
    mfe: float = 0.0
    mom_gt_exit_streak: int = 0
    stop_hit: bool = False


@dataclass(frozen=True)
class Fill:
    trade_date: date
    signal_date: date
    side: str
    code: str
    price: float
    shares: float
    notional: float
    reason: str
    entry_rank: int | None
    momentum_rank: int | None
    pnl_pct: float | None = None
    holding_days: int | None = None
    mae: float | None = None
    mfe: float | None = None


@dataclass(frozen=True)
class EquityPoint:
    trade_date: date
    equity: float
    cash: float
    cash_ratio: float
    n_positions: int
    daily_return: float
    drawdown: float
    turnover: float
    positions: str


@dataclass(frozen=True)
class ClosedTrade:
    code: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    return_pct: float
    holding_days: int
    mae: float
    mfe: float
    reason: str


@dataclass(frozen=True)
class StrategyResult:
    market: str
    spec: StrategySpec
    start: date
    end: date
    universe_size: int
    fills: tuple[Fill, ...]
    equity: tuple[EquityPoint, ...]
    closed_trades: tuple[ClosedTrade, ...]
    metrics: dict[str, Any]


__all__ = [
    "ClosedTrade",
    "EquityPoint",
    "Fill",
    "OhlcvBar",
    "OpenPosition",
    "StrategyResult",
    "StrategySpec",
]
