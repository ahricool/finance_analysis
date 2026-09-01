"""Small capability protocols implemented explicitly by providers."""

from __future__ import annotations

from typing import Protocol

from .models import (
    BatchBarResult,
    BatchInstrumentResult,
    BatchQuoteResult,
    DailyBarsRequest,
    InstrumentRequest,
    Market,
    MarketIndex,
    MarketStats,
    MinuteBarsRequest,
    QuoteRequest,
    SectorRankings,
)


class DailyBarsProvider(Protocol):
    def fetch_daily_bars(self, request: DailyBarsRequest) -> BatchBarResult: ...


class MinuteBarsProvider(Protocol):
    def fetch_minute_bars(self, request: MinuteBarsRequest) -> BatchBarResult: ...


class RealtimeProvider(Protocol):
    def fetch_quotes(self, request: QuoteRequest) -> BatchQuoteResult: ...


class MarketSnapshotProvider(Protocol):
    def fetch_market_snapshot(self, market: Market) -> BatchQuoteResult: ...


class MarketOverviewProvider(Protocol):
    def get_indices(self, market: Market) -> list[MarketIndex]: ...

    def get_market_stats(self, market: Market) -> MarketStats: ...

    def get_sector_rankings(self, market: Market) -> SectorRankings: ...


class InstrumentProvider(Protocol):
    def get_instrument_info(self, request: InstrumentRequest) -> BatchInstrumentResult: ...
