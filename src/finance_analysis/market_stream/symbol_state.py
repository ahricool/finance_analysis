"""Per-symbol and service-level runtime states."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from finance_analysis.stocks.markets import MarketType


class SymbolStatus(StrEnum):
    PENDING = "PENDING"
    WARMING = "WARMING"
    ACTIVE = "ACTIVE"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    REMOVING = "REMOVING"
    INACTIVE = "INACTIVE"
    ERROR = "ERROR"


class ConnectionStatus(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    SUBSCRIBING = "SUBSCRIBING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    RECONNECTING = "RECONNECTING"
    STOPPED = "STOPPED"


@dataclass(slots=True)
class SymbolRuntimeState:
    symbol: str
    market_type: MarketType
    trading_date: date | None = None
    status: SymbolStatus = SymbolStatus.PENDING
    generation: int = 0
    quote_subscribed: bool = False
    candlestick_1m_subscribed: bool = False
    bars_count: int = 0
    last_quote_at: datetime | None = None
    last_candle_at: datetime | None = None
    warmed_at: datetime | None = None
    error: str | None = None

    def redis_mapping(self, updated_at: datetime) -> dict[str, object]:
        return {
            "market_type": self.market_type,
            "trading_date": self.trading_date,
            "status": self.status,
            "quote_subscribed": self.quote_subscribed,
            "candlestick_1m_subscribed": self.candlestick_1m_subscribed,
            "bars_count": self.bars_count,
            "generation": self.generation,
            "last_quote_at": self.last_quote_at,
            "last_candle_at": self.last_candle_at,
            "warmed_at": self.warmed_at,
            "error": self.error,
            "updated_at": updated_at,
        }


@dataclass(frozen=True, slots=True)
class SubscriptionTarget:
    symbol: str
    market_type: MarketType
