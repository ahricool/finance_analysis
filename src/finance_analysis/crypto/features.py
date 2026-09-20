"""Decimal indicators on native Binance candles."""

from decimal import Decimal
from statistics import median

from finance_analysis.crypto.models import Kline


def ema(values: list[Decimal], period: int) -> Decimal:
    """SMA seed over period bars, then EMA alpha=2/(period+1)."""
    if len(values) < period:
        raise ValueError("Insufficient EMA warmup")
    value = sum(values[:period]) / period
    alpha = Decimal(2) / (period + 1)
    for current in values[period:]:
        value += alpha * (current - value)
    return value


def atr(bars: list[Kline], period: int = 14) -> Decimal:
    """Wilder ATR, seeded with the first 14 true ranges (requires a previous close)."""
    ranges = [
        max(row.high - row.low, abs(row.high - prev.close), abs(row.low - prev.close))
        for prev, row in zip(bars, bars[1:])
    ]
    if len(ranges) < period:
        raise ValueError("Insufficient ATR warmup")
    value = sum(ranges[:period]) / period
    for current in ranges[period:]:
        value = (value * (period - 1) + current) / period
    return value


def breakout(bars: list[Kline]) -> tuple[str, Decimal, Decimal | None]:
    previous, current = bars[-21:-1], bars[-1]
    if len(previous) < 20:
        raise ValueError("Insufficient breakout warmup")
    level = max(row.high for row in previous)
    volume = median(row.volume for row in previous)
    setup = "BREAKOUT" if current.close > level and current.volume > volume else "NONE"
    return setup, level, current.volume / volume if volume else None


def contiguous_tail(bars: list[Kline]) -> list[Kline]:
    """Never treat bars across a missing interval as consecutive indicator samples."""
    start = len(bars) - 1
    while start > 0 and bars[start - 1].close_time == bars[start].open_time:
        start -= 1
    return bars[max(0, start) :]
