"""Spot market regime rules."""

from decimal import Decimal


def market_regime(close: Decimal, ema20: Decimal, ema50: Decimal) -> str:
    if ema20 > ema50 and close > ema50:
        return "BULL"
    if ema20 < ema50 and close < ema50:
        return "BEAR"
    return "RANGE"
