"""Engine-neutral backtest request and result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol


@dataclass(frozen=True)
class DailyBar:
    trading_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float | None = None
    limit_up: float | None = None
    limit_down: float | None = None
    suspended: bool = False


@dataclass(frozen=True)
class BacktestRequest:
    engine: str
    strategy_key: str
    market: str
    code: str
    symbol_id: int
    start_date: date
    end_date: date
    initial_cash: float
    parameters: dict[str, Any]
    bars: tuple[DailyBar, ...]
    benchmark_code: str | None = None
    benchmark_bars: tuple[DailyBar, ...] = ()
    commission_rate: float = 0.0008
    stamp_tax_rate: float = 0.001
    transfer_fee_rate: float = 0.00001
    price_mode: str = "raw"


@dataclass
class BacktestTradeResult:
    code: str
    engine_order_id: str | None
    side: str
    signal_date: date
    order_date: date
    trade_date: date
    quantity: float
    price: float
    gross_amount: float
    commission: float = 0.0
    tax: float = 0.0
    other_fee: float = 0.0
    total_fee: float = 0.0
    cash_after: float = 0.0
    position_after: float = 0.0
    return_pct: float | None = None
    pnl: float | None = None
    exit_reason: str | None = None


@dataclass
class BacktestEquityResult:
    trading_date: date
    cash: float
    position_value: float
    total_equity: float
    benchmark_equity: float | None = None
    daily_return_pct: float = 0.0
    cumulative_return_pct: float = 0.0
    benchmark_return_pct: float | None = None
    drawdown_pct: float = 0.0
    position_pct: float = 0.0


@dataclass
class BacktestResult:
    engine: str
    engine_version: str
    strategy_key: str
    market: str
    code: str
    start_date: date
    end_date: date
    trades: list[BacktestTradeResult]
    equity_curve: list[BacktestEquityResult]
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    engine_debug: dict[str, Any] = field(default_factory=dict)


class BacktestEngine(Protocol):
    engine_key: str

    def run(self, request: BacktestRequest) -> BacktestResult:
        ...
