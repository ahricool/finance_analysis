"""Capability-based market-data integration package."""

from .models import (
    Adjustment,
    BatchBarResult,
    BatchInstrumentResult,
    BatchQuoteResult,
    DailyBarsRequest,
    InstrumentInfo,
    Market,
    MarketBar,
    MarketQuote,
    MinuteBarsRequest,
)
from .registry import ProviderConfigurationError, ProviderRegistry
from .router import MarketDataRouter
from .service import MarketDataService

__all__ = [
    "Adjustment",
    "BatchBarResult",
    "BatchInstrumentResult",
    "BatchQuoteResult",
    "DailyBarsRequest",
    "InstrumentInfo",
    "Market",
    "MarketBar",
    "MarketDataRouter",
    "MarketDataService",
    "MarketQuote",
    "MinuteBarsRequest",
    "ProviderConfigurationError",
    "ProviderRegistry",
]
