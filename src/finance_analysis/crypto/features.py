"""Deterministic UTC aggregation and Decimal indicators (no partial bars)."""

from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median

from finance_analysis.crypto.models import Bar, Kline


def aggregate(klines: list[Kline], minutes: int, as_of: datetime) -> list[Bar]:
    if minutes not in (15, 60):
        raise ValueError("Only 15m and 1h aggregates are supported")
    groups: dict[datetime, dict[datetime, Kline]] = {}
    for row in klines:
        if not row.closed or row.close_time > as_of:
            continue
        start = row.open_time.replace(minute=(row.open_time.minute // minutes) * minutes)
        groups.setdefault(start, {})[row.open_time] = row
    result = []
    for start, rows in sorted(groups.items()):
        if start + timedelta(minutes=minutes) > as_of:
            continue
        if any(start + timedelta(minutes=i) not in rows for i in range(minutes)):
            continue
        ordered = [rows[start + timedelta(minutes=i)] for i in range(minutes)]
        result.append(
            Bar(
                start,
                start + timedelta(minutes=minutes),
                ordered[0].open,
                max(r.high for r in ordered),
                min(r.low for r in ordered),
                ordered[-1].close,
                sum((r.volume for r in ordered), Decimal(0)),
            )
        )
    return result


def ema(values: list[Decimal], period: int) -> Decimal:
    """SMA seed over period bars, then EMA alpha=2/(period+1)."""
    if len(values) < period:
        raise ValueError("Insufficient EMA warmup")
    value = sum(values[:period]) / period
    alpha = Decimal(2) / (period + 1)
    for current in values[period:]:
        value += alpha * (current - value)
    return value


def atr(bars: list[Bar], period: int = 14) -> Decimal:
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


def breakout(bars: list[Bar]) -> tuple[str, Decimal, Decimal | None]:
    previous, current = bars[-21:-1], bars[-1]
    if len(previous) < 20:
        raise ValueError("Insufficient breakout warmup")
    level = max(row.high for row in previous)
    volume = median(row.volume for row in previous)
    setup = "BREAKOUT" if current.close > level and current.volume > volume else "NONE"
    return setup, level, current.volume / volume if volume else None


def contiguous_tail(bars: list[Bar]) -> list[Bar]:
    """Never treat bars across a missing interval as consecutive indicator samples."""
    start = len(bars) - 1
    while start > 0 and bars[start - 1].close_time == bars[start].open_time:
        start -= 1
    return bars[max(0, start) :]
