# -*- coding: utf-8 -*-
"""Shared Trade Engine DTOs. Strategies return TradeSignal; state stays in JSON dicts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Protocol, Sequence

from finance_analysis.portfolio.models import ResolvedPosition  # pragma: allowlist secret

Action = Literal["HOLD", "WATCH", "REDUCE", "EXIT", "WARNING"]
ACTION_RANK = {"EXIT": 4, "REDUCE": 3, "WATCH": 2, "WARNING": 1, "HOLD": 0}


@dataclass(frozen=True, slots=True)
class QuoteView:
    price: Decimal
    quote_as_of: datetime | None
    valid: bool
    stale: bool = False


@dataclass(frozen=True, slots=True)
class MarketContext:
    market: str
    as_of: datetime
    trading_date: datetime | None
    session_open: bool
    regime: str | None = None
    breadth: dict[str, Any] = field(default_factory=dict)
    indices: dict[str, Any] = field(default_factory=dict)
    sectors: dict[str, Any] = field(default_factory=dict)
    sentiment: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TradeSignal:
    strategy_key: str
    strategy_version: str
    market: str
    account_id: str | None
    position_id: str | None
    symbol: str | None
    action: Action
    suggested_target_quantity: Decimal | None
    reason: str
    evidence: dict[str, Any]
    evaluated_at: datetime
    signal_key: str


@dataclass(frozen=True, slots=True)
class AggregatedSignal:
    action: Action
    suggested_target_quantity: Decimal | None
    reasons: tuple[str, ...]
    signals: tuple[TradeSignal, ...]


class PositionTradeStrategy(Protocol):
    key: str
    version: str
    market: str | None

    def evaluate(
        self,
        position: ResolvedPosition,
        market_context: MarketContext,
        quote: QuoteView | None,
        bars: Sequence,
        state: dict[str, Any],
    ) -> list[TradeSignal]:
        ...


class PortfolioTradeStrategy(Protocol):
    key: str
    version: str
    market: str | None

    def evaluate(
        self,
        positions: Sequence[ResolvedPosition],
        quotes: dict[str, QuoteView],
        market_context: MarketContext,
        states: dict[str, dict[str, Any]],
        *,
        cash: Decimal,
        policy: Any,
    ) -> list[TradeSignal]:
        ...
