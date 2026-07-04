"""Pydantic contracts for the unified backtest API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BacktestConfigRequest(BaseModel):
    engine: str
    strategy_key: str
    market: str
    code: str
    start_date: date
    end_date: date
    parameters: dict[str, Any] = Field(default_factory=dict)
    benchmark_code: str | None = None

    @field_validator("engine", "strategy_key")
    @classmethod
    def lower_key(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("market", "code", "benchmark_code")
    @classmethod
    def upper_key(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else value


class BacktestRunCreate(BacktestConfigRequest):
    initial_cash: float = Field(default=100000, gt=0)


class EngineResponse(BaseModel):
    key: str
    name: str
    description: str
    display_order: int
    is_default: bool
    recommended: bool
    available: bool
    unavailable_reason: str | None
    version: str | None
    supported_markets: list[str] | tuple[str, ...]
    supported_strategies: list[str] | tuple[str, ...]


class StrategyParameterResponse(BaseModel):
    key: str
    name: str
    type: str
    default: int
    minimum: int
    maximum: int


class StrategyResponse(BaseModel):
    key: str
    name: str
    description: str
    version: str
    frequency: str
    supported_markets: list[str] | tuple[str, ...]
    supported_engines: list[str] | tuple[str, ...]
    parameters: list[StrategyParameterResponse] | tuple[StrategyParameterResponse, ...]


class SymbolResponse(BaseModel):
    id: int
    market: str
    code: str
    name: str
    lot_size: int | None = None


class PreflightResponse(BaseModel):
    ready: bool
    engine: str
    engine_version: str | None
    strategy_key: str
    market: str
    code: str
    available_date_from: date | None
    available_date_to: date | None
    requested_trading_days: int
    available_trading_days: int
    coverage_ratio: float
    warmup_days: int
    warnings: list[str]
    errors: list[str]


class BacktestRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uid: int
    task_id: str | None
    engine: str
    engine_version: str | None
    engine_config: dict[str, Any]
    strategy_key: str
    strategy_name: str
    strategy_version: str
    market: str
    symbol_id: int
    code: str
    start_date: date
    end_date: date
    initial_cash: float
    benchmark_code: str | None
    parameters: dict[str, Any]
    price_mode: str
    market_rule_version: str
    status: str
    progress: int
    summary: dict[str, Any]
    warnings: list[str]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class BacktestRunListResponse(BaseModel):
    items: list[BacktestRunResponse]
    total: int
    page: int
    page_size: int


class BacktestTradeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    code: str
    engine_order_id: str | None
    side: str
    signal_date: date
    order_date: date
    trade_date: date
    quantity: float
    price: float
    gross_amount: float
    commission: float
    tax: float
    other_fee: float
    total_fee: float
    cash_after: float
    position_after: float
    return_pct: float | None
    pnl: float | None
    exit_reason: str | None


class BacktestTradeListResponse(BaseModel):
    items: list[BacktestTradeResponse]
    total: int
    page: int
    page_size: int


class BacktestEquityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trading_date: date
    cash: float
    position_value: float
    total_equity: float
    benchmark_equity: float | None
    daily_return_pct: float
    cumulative_return_pct: float
    benchmark_return_pct: float | None
    drawdown_pct: float


class BacktestEquityListResponse(BaseModel):
    items: list[BacktestEquityResponse]
