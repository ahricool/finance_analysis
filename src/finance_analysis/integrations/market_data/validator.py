"""Quality gates applied after normalization and before data leaves the router."""

from __future__ import annotations

import math
from datetime import timezone
from typing import Iterable

from .models import MarketBar, MarketQuote


class MarketDataValidationError(ValueError):
    pass


def validate_bars(bars: Iterable[MarketBar]) -> list[MarketBar]:
    validated: list[MarketBar] = []
    for bar in bars:
        prices = (bar.open, bar.high, bar.low, bar.close)
        if not all(math.isfinite(value) and value > 0 for value in prices):
            raise MarketDataValidationError(f"{bar.symbol} {bar.trade_date}: OHLC must be finite and positive")
        if bar.high < max(bar.open, bar.close, bar.low) or bar.low > min(bar.open, bar.close, bar.high):
            raise MarketDataValidationError(f"{bar.symbol} {bar.trade_date}: inconsistent OHLC range")
        if bar.volume < 0:
            raise MarketDataValidationError(f"{bar.symbol} {bar.trade_date}: volume must be nonnegative")
        if bar.amount is not None and (not math.isfinite(bar.amount) or bar.amount < 0):
            raise MarketDataValidationError(f"{bar.symbol} {bar.trade_date}: amount must be null or nonnegative")
        if bar.interval == "1d" and bar.bar_time is not None:
            raise MarketDataValidationError(f"{bar.symbol} {bar.trade_date}: daily bar_time must be null")
        if bar.interval != "1d" and (bar.bar_time is None or bar.bar_time.tzinfo != timezone.utc):
            raise MarketDataValidationError(f"{bar.symbol} {bar.trade_date}: minute bar_time must be UTC")
        validated.append(bar)
    return validated


def validate_quote(quote: MarketQuote) -> MarketQuote:
    if quote.price is None or not math.isfinite(quote.price) or quote.price <= 0:
        raise MarketDataValidationError(f"{quote.symbol}: realtime price must be finite and positive")
    if quote.volume is not None and quote.volume < 0:
        raise MarketDataValidationError(f"{quote.symbol}: realtime volume must be nonnegative")
    if quote.amount is not None and (not math.isfinite(quote.amount) or quote.amount < 0):
        raise MarketDataValidationError(f"{quote.symbol}: realtime amount must be null or nonnegative")
    return quote
