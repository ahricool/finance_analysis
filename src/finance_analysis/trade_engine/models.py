# -*- coding: utf-8 -*-
"""Trade Engine DTOs. Strategies return at most one candidate per position."""

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
    reason: str
    comment: str | None = None
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
    llm_comment: str | None
    reviewed_by_llm: bool
    evidence: dict[str, Any]
    evaluated_at: datetime
    signal_key: str


class PositionTradeStrategy(Protocol):
    key: str
    version: str
    market: str | None

    def evaluate(self, context: PositionContext) -> list[TradeSignalCandidate]:
        ...


def five_minute_stamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    stamp = value.replace(second=0, microsecond=0)
    return stamp.replace(minute=(stamp.minute // 5) * 5).isoformat()


def one_candidate(signals: list[TradeSignalCandidate]) -> list[TradeSignalCandidate]:
    if len(signals) <= 1:
        return signals
    ranked = max(signals, key=lambda item: (1 if item.hard else 0, ACTION_RANK.get(item.action, 0)))
    reason = ";".join(item.reason for item in signals if item.reason)
    return [
        TradeSignalCandidate(
            market=ranked.market,
            account_id=ranked.account_id,
            position_id=ranked.position_id,
            symbol=ranked.symbol,
            strategy_key=ranked.strategy_key,
            strategy_version=ranked.strategy_version,
            action=ranked.action,
            suggested_target_quantity=ranked.suggested_target_quantity,
            severity=ranked.severity,
            reason=reason or ranked.reason,
            evidence=ranked.evidence,
            evaluated_at=ranked.evaluated_at,
            signal_key=ranked.signal_key,
        )
    ]
