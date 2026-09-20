# -*- coding: utf-8 -*-
"""Trade Engine DTOs. Strategies return candidates; confirmed signals are immutable."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Protocol, Sequence

from .bars import NormalizedBar  # pragma: allowlist secret
from .indicators import BarIndicators  # pragma: allowlist secret
from ..portfolio.models import ResolvedPosition  # pragma: allowlist secret

Action = Literal["HOLD", "WATCH", "REDUCE", "EXIT"]
CandidateAction = Literal["WATCH", "REDUCE", "EXIT"]
Severity = Literal["hard", "soft"]
ReviewVerdict = Literal["CONFIRM", "REJECT"]
ACTION_RANK = {"EXIT": 4, "REDUCE": 3, "WATCH": 2, "HOLD": 0}


@dataclass(frozen=True, slots=True)
class QuoteView:
    price: Decimal
    quote_as_of: datetime | None
    valid: bool
    stale: bool = False


@dataclass
class PositionContext:
    """Per-holding analysis input. Never contains full-market breadth or scanners."""

    market: str
    symbol: str
    position: ResolvedPosition
    quote: QuoteView | None
    five_minute_bars: Sequence[NormalizedBar] = ()
    daily_bars: Sequence[Any] = ()
    technical_indicators: Sequence[BarIndicators] = ()
    strategy_state: dict[str, Any] = field(default_factory=dict)
    now: datetime | None = None
    bars_stale: bool = False
    latest_expected: datetime | None = None
    policy: Any = None

    @property
    def lots(self):
        return self.position.lots


@dataclass(frozen=True, slots=True)
class TradeSignalCandidate:
    market: str
    account_id: str | None
    position_id: str | None
    symbol: str | None
    strategy_key: str
    strategy_version: str
    action: CandidateAction
    suggested_target_quantity: Decimal | None
    severity: Severity
    reason: str
    evidence: dict[str, Any]
    evaluated_at: datetime
    signal_key: str

    @property
    def hard(self) -> bool:
        return self.severity == "hard" or bool((self.evidence or {}).get("hard"))


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    decision: ReviewVerdict
    action: CandidateAction
    target_quantity: Decimal | None
    reason: str
    failed: bool = False


@dataclass(frozen=True, slots=True)
class TradeSignal:
    strategy_key: str
    strategy_version: str
    market: str
    account_id: str | None
    position_id: str | None
    symbol: str | None
    action: CandidateAction
    suggested_target_quantity: Decimal | None
    reason: str
    deterministic_reason: str
    llm_reason: str | None
    reviewed_by_llm: bool
    evidence: dict[str, Any]
    evaluated_at: datetime
    signal_key: str


@dataclass(frozen=True, slots=True)
class AggregatedSignal:
    action: Action
    suggested_target_quantity: Decimal | None
    reasons: tuple[str, ...]
    candidates: tuple[TradeSignalCandidate, ...] = ()


class PositionTradeStrategy(Protocol):
    key: str
    version: str
    market: str | None

    def evaluate(self, context: PositionContext) -> list[TradeSignalCandidate]:
        ...
