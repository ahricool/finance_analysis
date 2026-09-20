"""BTC strategy REST contracts. Decimal JSON values are strings."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class CryptoStateResponse(BaseModel):
    symbol: Literal["BTCUSDT"] = "BTCUSDT"
    position_state: Literal["FLAT", "LONG"]
    position_pct: Decimal
    average_entry_price: Decimal | None = None
    entry_price: Decimal | None = None
    entry_time: datetime | None = None
    highest_price_since_entry: Decimal | None = None
    initial_stop: Decimal | None = None
    trailing_stop: Decimal | None = None
    updated_at: datetime | None = None


class CryptoSnapshotResponse(BaseModel):
    symbol: Literal["BTCUSDT"] = "BTCUSDT"
    evaluated_at: datetime
    regime: Literal["BULL", "BEAR", "RANGE", "UNKNOWN"]
    setup: Literal["BREAKOUT", "NONE"]
    action: Literal["BUY", "WAIT", "HOLD", "EXIT"]
    price: Decimal
    ema20_1h: Decimal | None = None
    ema50_1h: Decimal | None = None
    ema20_15m: Decimal | None = None
    breakout_level_15m: Decimal | None = None
    volume_ratio_15m: Decimal | None = None
    atr14_15m: Decimal | None = None
    initial_stop: Decimal | None = None
    trailing_stop: Decimal | None = None
    position_state: Literal["FLAT", "LONG"]
    position_before: Decimal | None = None
    position_after: Decimal | None = None
    position_delta: Decimal | None = None
    average_entry_price: Decimal | None = None
    reason: str


class CryptoOverviewResponse(BaseModel):
    symbol: Literal["BTCUSDT"] = "BTCUSDT"
    strategy: CryptoSnapshotResponse | None
    state: CryptoStateResponse


class CryptoSignalsResponse(BaseModel):
    items: list[CryptoSnapshotResponse]


class CryptoPositionResponse(BaseModel):
    position_pct: Decimal
    average_entry_price: Decimal | None


class CryptoExecutionResponse(BaseModel):
    evaluated_at: datetime
    price: Decimal
    position_before: Decimal
    position_after: Decimal
    position_delta: Decimal
    action: str
    reason: str


class CryptoTradeResponse(BaseModel):
    entry_time: datetime
    exit_time: datetime
    holding_seconds: int
    average_entry_price: Decimal
    exit_price: Decimal
    realized_return: Decimal


class CryptoEquityPoint(BaseModel):
    evaluated_at: datetime
    equity: Decimal
    drawdown: Decimal


class CryptoPerformanceResponse(BaseModel):
    performance_start_at: datetime | None
    performance_end_at: datetime | None
    current_position: CryptoPositionResponse
    execution_count: int
    completed_cycles: int
    win_count: int
    loss_count: int
    win_rate: Decimal | None
    average_return: Decimal | None
    cumulative_return: Decimal
    max_drawdown: Decimal
    best_trade: Decimal | None
    worst_trade: Decimal | None
    recent_executions: list[CryptoExecutionResponse]
    recent_trades: list[CryptoTradeResponse]
    equity_curve: list[CryptoEquityPoint]
