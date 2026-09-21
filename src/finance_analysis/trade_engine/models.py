# -*- coding: utf-8 -*-
"""Trade Engine DTOs. Strategies emit stateless signals; LLM owns decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol, Sequence

from ..portfolio.models import ResolvedPosition  # pragma: allowlist secret

TradeAction = Literal["BUY", "ADD", "REDUCE", "EXIT"]
FinalAction = Literal["BUY", "ADD", "REDUCE", "EXIT", "NO_ACTION"]
TRADE_ACTIONS = frozenset({"BUY", "ADD", "REDUCE", "EXIT"})
ValuationSource = Literal["QUOTE", "DAILY_FALLBACK", "UNAVAILABLE"]
LLM_SUMMARY_MAX = 8000
LLM_DAILY_BARS = 15
TRADE_HISTORY_LIMIT = 20


@dataclass(frozen=True, slots=True)
class QuoteView:
    price: Decimal | None
    quote_as_of: datetime | None
    valid: bool
    stale: bool = False
    today_open: Decimal | None = None
    today_high: Decimal | None = None
    today_low: Decimal | None = None
    today_volume: int | None = None
    today_turnover: Decimal | None = None
    pre_close: Decimal | None = None
    change_pct: Decimal | None = None


@dataclass(frozen=True, slots=True)
class DailyBar:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = 0


@dataclass(frozen=True, slots=True)
class LotRisk:
    lot_id: str
    role: str
    quantity: Decimal
    entry_price: Decimal
    high_watermark: Decimal | None
    profit_stage: str
    active_stop: Decimal | None
    structure_stop: Decimal | None
    stop_effective_at: datetime | None = None
    open_risk: Decimal | None = None


@dataclass(frozen=True, slots=True)
class PositionRisk:
    lots: tuple[LotRisk, ...] = ()
    profit_stage: str = "UNKNOWN"
    active_stop: Decimal | None = None
    high_watermark: Decimal | None = None
    dump: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MarketPortfolioContext:
    """One market's account valuation. Shared by add_v1 and portfolio_risk_v1."""

    market: str
    cash: Decimal
    positions: tuple[ResolvedPosition, ...]
    strategy_positions: tuple[ResolvedPosition, ...]
    valuation_prices: dict[str, Decimal]
    valuation_sources: dict[str, ValuationSource]
    market_values: dict[str, Decimal]
    nav: Decimal | None
    valuation_complete: bool
    incomplete_symbols: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TradeHistoryItem:
    side: str
    quantity: Decimal
    price: Decimal
    executed_at: datetime
    note: str | None = None


@dataclass
class PositionContext:
    """Per-holding analysis input. Never contains full-market breadth or scanners."""

    market: str
    symbol: str
    position: ResolvedPosition
    quote: QuoteView | None
    daily_bars: Sequence[DailyBar] = ()
    risk: PositionRisk = field(default_factory=PositionRisk)
    now: datetime | None = None
    policy: Any = None
    cash: Decimal = Decimal("0")
    market_nav: Decimal = Decimal("0")
    position_value: Decimal = Decimal("0")
    valuation_source: ValuationSource | None = None
    valuation_complete: bool = True
    trade_history: tuple[TradeHistoryItem, ...] = ()

    @property
    def lots(self):
        return self.position.lots


@dataclass(frozen=True, slots=True)
class StrategySignal:
    strategy_key: str
    strategy_version: str
    market: str
    account_id: str | None
    position_id: str | None
    symbol: str | None
    action: TradeAction
    suggested_quantity: Decimal | None
    suggested_target_quantity: Decimal | None
    reason: str
    evidence: dict[str, Any]
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class SymbolRiskFacts:
    weight: Decimal | None
    max_weight: Decimal
    open_risk: Decimal | None
    risk_limit: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioRiskFacts:
    market: str
    nav: Decimal | None
    cash: Decimal
    gross_exposure: Decimal | None
    max_gross_exposure: Decimal
    total_open_risk: Decimal | None
    total_open_risk_limit: Decimal
    valuation_complete: bool
    incomplete_symbols: tuple[str, ...] = ()
    positions: dict[str, SymbolRiskFacts] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PreviousLLMState:
    summary: str = ""
    last_decision: dict[str, Any] = field(default_factory=dict)
    last_decision_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MarketTradeDecisionContext:
    market: str
    cash: Decimal
    nav: Decimal | None
    gross_exposure: Decimal | None
    policy: dict[str, Any]
    positions: tuple[dict[str, Any], ...]
    strategy_signals: tuple[StrategySignal, ...]
    portfolio_risk: PortfolioRiskFacts
    previous: PreviousLLMState
    recent_signals: tuple[dict[str, Any], ...] = ()
    web_search_available: bool = False
    evaluated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PositionTarget:
    position_id: str
    symbol: str
    current_quantity: Decimal
    target_quantity: Decimal
    action: FinalAction
    reason: str


@dataclass(frozen=True, slots=True)
class MarketDecision:
    market: str
    portfolio_reason: str
    positions: tuple[PositionTarget, ...]
    state_summary: str
    failed: bool = False


@dataclass(frozen=True, slots=True)
class TradeSignal:
    strategy_key: str
    strategy_version: str
    market: str
    account_id: str | None
    position_id: str | None
    symbol: str | None
    action: TradeAction
    suggested_quantity: Decimal | None
    suggested_target_quantity: Decimal | None
    reason: str
    llm_reason: str | None
    evidence: dict[str, Any]
    evaluated_at: datetime
    signal_key: str
    reviewed_by_llm: bool = True


class PositionTradeStrategy(Protocol):
    key: str
    version: str
    market: str | None

    def evaluate(self, context: PositionContext) -> list[StrategySignal]:
        ...
