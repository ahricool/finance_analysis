# -*- coding: utf-8 -*-
"""Trade Engine DTOs. Strategies emit explicit BUY/ADD/REDUCE/EXIT proposals."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol, Sequence

from ..portfolio.models import ResolvedPosition  # pragma: allowlist secret

TradeAction = Literal["BUY", "ADD", "REDUCE", "EXIT"]
FinalAction = Literal["BUY", "ADD", "REDUCE", "EXIT", "NO_ACTION"]
TRADE_ACTIONS = frozenset({"BUY", "ADD", "REDUCE", "EXIT"})


@dataclass(frozen=True, slots=True)
class QuoteView:
    price: Decimal
    quote_as_of: datetime | None
    valid: bool
    stale: bool = False


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


@dataclass(frozen=True, slots=True)
class PositionRisk:
    lots: tuple[LotRisk, ...] = ()
    profit_stage: str = "UNKNOWN"
    active_stop: Decimal | None = None
    high_watermark: Decimal | None = None
    dump: dict[str, Any] = field(default_factory=dict)


@dataclass
class PositionContext:
    """Per-holding analysis input. Never contains full-market breadth or scanners."""

    market: str
    symbol: str
    position: ResolvedPosition
    quote: QuoteView | None
    daily_bars: Sequence[DailyBar] = ()
    strategy_state: dict[str, Any] = field(default_factory=dict)
    risk: PositionRisk = field(default_factory=PositionRisk)
    now: datetime | None = None
    policy: Any = None
    cash: Decimal = Decimal("0")
    market_nav: Decimal = Decimal("0")
    position_value: Decimal = Decimal("0")

    @property
    def lots(self):
        return self.position.lots


@dataclass(frozen=True, slots=True)
class StrategyProposal:
    market: str
    account_id: str | None
    position_id: str | None
    symbol: str | None
    strategy_key: str
    strategy_version: str
    action: TradeAction
    suggested_quantity: Decimal | None
    suggested_target_quantity: Decimal | None
    reason: str
    evidence: dict[str, Any]
    evaluated_at: datetime
    proposal_key: str


@dataclass(frozen=True, slots=True)
class PortfolioWarning:
    market: str
    account_id: str | None
    position_id: str | None
    symbol: str | None
    kind: str
    reason: str
    current: Decimal
    limit: Decimal
    evidence: dict[str, Any]
    evaluated_at: datetime
    warning_key: str


@dataclass(frozen=True, slots=True)
class StrategyAssessment:
    strategy: str
    action: str
    decision: str
    reason: str


@dataclass(frozen=True, slots=True)
class FinalDecision:
    position_id: str
    symbol: str | None
    action: FinalAction
    quantity: Decimal | None
    target_quantity: Decimal | None
    reason: str
    assessments: tuple[StrategyAssessment, ...] = ()
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

    def evaluate(self, context: PositionContext) -> list[StrategyProposal]:
        ...
