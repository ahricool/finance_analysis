# -*- coding: utf-8 -*-
"""Resolved portfolio DTOs. Currency is inferred from market; values are Decimal."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from finance_analysis.integrations.market_data.normalizer import MARKET_CURRENCIES  # pragma: allowlist secret
from finance_analysis.integrations.market_data.models import Market  # pragma: allowlist secret

PositionSource = Literal["DB", "GOOGLE"]
Coverage = Literal["DB", "EXTERNAL", "EXTERNAL_ONLY"]
LotRole = Literal["CORE", "ADDON"]
AssetType = Literal["STOCK", "ETF", "OPTION"]


def currency_for_market(market: str) -> str:
    try:
        return MARKET_CURRENCIES[Market(market)]
    except Exception:
        return "USD" if market == "US" else "CNY"


@dataclass(frozen=True, slots=True)
class ResolvedLot:
    lot_id: str
    role: LotRole
    quantity: Decimal
    entry_price: Decimal
    entry_time: datetime


@dataclass(frozen=True, slots=True)
class ResolvedPosition:
    source: PositionSource
    coverage: Coverage
    uid: int
    market: str
    account_id: str
    position_id: str
    symbol: str
    asset_type: str
    quantity: Decimal
    average_cost: Decimal
    opened_at: datetime | None = None
    lots: tuple[ResolvedLot, ...] = ()
    quote_price: Decimal | None = None
    name: str | None = None
    trade_engine_enabled: bool = True
    had_addon: bool = False

    @property
    def is_option(self) -> bool:
        return (self.asset_type or "").upper() == "OPTION"

    @property
    def trade_engine_eligible(self) -> bool:
        return (
            (not self.is_option)
            and self.quantity > 0
            and self.asset_type.upper() in {"STOCK", "ETF"}
            and bool(self.trade_engine_enabled)
        )


@dataclass(frozen=True, slots=True)
class ResolvedAccount:
    source: PositionSource
    uid: int
    account_id: str
    name: str
    market: str
    cash: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class ResolvedPortfolio:
    uid: int
    accounts: tuple[ResolvedAccount, ...]
    positions: tuple[ResolvedPosition, ...]
    warnings: tuple[str, ...] = ()
    google_generation: int | None = None

    def positions_for_market(self, market: str) -> tuple[ResolvedPosition, ...]:
        return tuple(item for item in self.positions if item.market == market)

    def stock_positions(self, market: str | None = None) -> tuple[ResolvedPosition, ...]:
        rows = self.positions if market is None else self.positions_for_market(market)
        return tuple(item for item in rows if item.trade_engine_eligible)


@dataclass(frozen=True, slots=True)
class TradeMarkerOperation:
    executed_at: datetime
    side: Literal["BUY", "SELL"]
    quantity: Decimal
    price: Decimal
    note: str | None = None


@dataclass(frozen=True, slots=True)
class TradeMarker:
    timestamp: datetime
    type: Literal["B", "S", "T"]
    operations: tuple[TradeMarkerOperation, ...] = field(default_factory=tuple)
    label: str | None = None
    strategy_key: str | None = None
    strategy_name: str | None = None
