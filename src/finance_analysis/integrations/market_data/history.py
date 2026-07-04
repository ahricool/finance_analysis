"""Explicit provider contract for unadjusted historical OHLCV synchronization."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

import pandas as pd


class SymbolIdentity(Protocol):
    market: str
    code: str


@dataclass(frozen=True)
class HistoricalProviderError(RuntimeError):
    provider: str
    market: str
    code: str
    data_type: str
    requested_range: str
    reason: str
    retryable: bool = False

    def __str__(self) -> str:
        return (
            f"provider={self.provider} market={self.market} code={self.code} "
            f"data_type={self.data_type} requested_range={self.requested_range} "
            f"retryable={self.retryable} reason={self.reason}"
        )


class HistoricalMarketDataProvider(ABC):
    """Providers return normalized, unadjusted bars only."""

    name: str
    source_priority: int

    @abstractmethod
    def fetch_daily_bars(self, symbol: SymbolIdentity, start_date: date, end_date: date) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def fetch_minute_bars(
        self,
        symbol: SymbolIdentity,
        start_time: datetime,
        end_time: datetime,
        session_type: str = "regular",
    ) -> pd.DataFrame:
        raise NotImplementedError


DAILY_COLUMNS = ("date", "open", "high", "low", "close", "volume", "amount")
MINUTE_COLUMNS = ("bar_time", "open", "high", "low", "close", "volume", "amount")
SOURCE_PRIORITY = {"LongbridgeFetcher": 100, "YfinanceFetcher": 50}


__all__ = [
    "DAILY_COLUMNS",
    "MINUTE_COLUMNS",
    "SOURCE_PRIORITY",
    "HistoricalMarketDataProvider",
    "HistoricalProviderError",
    "SymbolIdentity",
]
