"""Per-symbol and service-level runtime states."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


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
