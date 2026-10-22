"""Explicit stock simulation HTTP contract; financial values are ratios and local currency."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Market = Literal["CN", "US"]


class Rule(BaseModel):
    label: str
    text: str


class Strategy(BaseModel):
    key: str
    version: str
    name: str
    markets: tuple[Market, ...]
    family: str
    slots: int
    atr: float
    account_dd: float
    cooldown: int
    risk_engine: str
    breadth: bool
    breakout: bool
    source_id: str
    rules: list[Rule]


class Candidate(BaseModel):
    code: str
    name: str
    score: float
    atr: float
    type: str
    signal_close: float


class Plan(BaseModel):
    signal_date: date
    execution_date: date
    status: Literal["PAUSED", "READY"]
    candidates: list[Candidate]
    exits: dict[str, list[str]]


class Position(BaseModel):
    name: str
    quantity: float
    entry_price: float
    mark: float
    mark_date: date
    peak: float
    stop: float | None
    pending_exit: list[str]


class Fill(BaseModel):
    code: str
    name: str
    action: Literal["BUY", "SELL"]
    quantity: float
    price: float
    amount: float
    pnl: float | None
    reasons: list[str]
    signal_date: date


class Ledger(BaseModel):
    cash: float
    positions: dict[str, Position]
    fills: list[Fill]
    adjustments: list[dict[str, Any]]
    blocked: list[dict[str, Any]]
    plan: Plan
    warnings: list[str]
    stale_codes: list[str]
    sessions: int
    closed_rounds: int
    win_rate: float | None
    annual_turnover: float
    pause_remaining: int
    breadth: float | None
    breadth_denominator: int | None
    provenance: dict[str, Any]
    computed_at: datetime
    replayed: bool
    next_is_historical: bool


class Metrics(BaseModel):
    trade_date: date
    nav: float
    daily_return: float
    total_return: float
    cagr: float | None
    max_drawdown: float
    drawdown: float
    exposure: float
    benchmark_return: float | None


class Day(Metrics):
    payload: Ledger
    created_at: datetime


class Run(BaseModel):
    trade_date: date
    status: Literal["success", "waiting", "failed"]
    reason: str | None
    attempts: int
    updated_at: datetime


class Item(BaseModel):
    strategy: Strategy
    latest: Day | None
    last_run: Run | None
    start_date: date | None
    status: Literal["success", "waiting", "failed", "not_started", "catching_up"]


class Overview(BaseModel):
    expected_date: date
    market: Market
    items: list[Item]


class Detail(BaseModel):
    expected_date: date
    market: Market
    strategy: Strategy
    latest: Day | None
    last_run: Run | None
    start_date: date | None
    universe: dict[str, Any] | None
    curve: list[Metrics]
    days: list[Day]
    next_before: date | None


class RunRequest(BaseModel):
    market: Market | None = None
    strategy_key: str | None = Field(None, min_length=1, max_length=64)


class RunResponse(BaseModel):
    task_id: str
    status: Literal["pending"] = "pending"
