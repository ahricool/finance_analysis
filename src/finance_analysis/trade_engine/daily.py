# -*- coding: utf-8 -*-
"""Daily-bar helpers for medium-term Trade Engine strategies."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from statistics import median
from typing import Iterable, Sequence

from ..market_review.trading_calendar import get_completed_trading_days  # pragma: allowlist secret
from ..portfolio.models import ResolvedPosition  # pragma: allowlist secret
from .models import DailyBar, LLM_DAILY_BARS  # pragma: allowlist secret

HISTORY_WARMUP_DAYS = 30


def sma(values: Sequence[Decimal], period: int) -> Decimal | None:
    if period <= 0 or len(values) < period:
        return None
    window = values[-period:]
    return sum(window, start=Decimal("0")) / Decimal(period)


def sma_series(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    out: list[Decimal | None] = []
    for index in range(len(values)):
        if index + 1 < period:
            out.append(None)
            continue
        window = values[index + 1 - period : index + 1]
        out.append(sum(window, start=Decimal("0")) / Decimal(period))
    return out


def true_range(current: DailyBar, previous: DailyBar | None) -> Decimal:
    if previous is None:
        return current.high - current.low
    high_low = current.high - current.low
    high_close = abs(current.high - previous.close)
    low_close = abs(current.low - previous.close)
    return max(high_low, high_close, low_close)


def atr(bars: Sequence[DailyBar], period: int) -> Decimal | None:
    if period <= 0 or len(bars) < period + 1:
        return None
    ranges: list[Decimal] = []
    previous = None
    for bar in bars:
        ranges.append(true_range(bar, previous))
        previous = bar
    window = ranges[-period:]
    return sum(window, start=Decimal("0")) / Decimal(period)


def ma_slope(series: Sequence[Decimal | None], lookback: int = 5) -> Decimal | None:
    valid = [item for item in series if item is not None]
    if lookback <= 0 or len(valid) < lookback + 1:
        return None
    latest = valid[-1]
    prior = valid[-1 - lookback]
    return (latest - prior) / Decimal(lookback)


def volume_median(bars: Sequence[DailyBar], period: int = 20) -> Decimal | None:
    if period <= 0 or len(bars) < period:
        return None
    values = [Decimal(bar.volume) for bar in bars[-period:] if bar.volume > 0]
    if len(values) < max(5, period // 2):
        return None
    return Decimal(str(median(values)))


def last_complete_date(bars: Sequence[DailyBar]) -> date | None:
    if not bars:
        return None
    return bars[-1].trade_date


def latest_completed_trading_day(market: str, now: datetime) -> date | None:
    days = get_completed_trading_days(market.lower(), 1, current_time=now)
    return days[-1] if days else None


def completed_daily_bars(bars: Sequence[DailyBar], cutoff: date | None) -> list[DailyBar]:
    if cutoff is None:
        return []
    return [bar for bar in bars if bar.trade_date <= cutoff]


def legalize_quantity(quantity: Decimal, market: str) -> Decimal:
    del market
    if quantity <= 0:
        return Decimal("0")
    return quantity.quantize(Decimal("1"), rounding=ROUND_DOWN)


def extension_atr(close: Decimal, ma_fast: Decimal, atr_value: Decimal) -> Decimal | None:
    if atr_value <= 0:
        return None
    return (close - ma_fast) / atr_value


def history_start_date(
    positions: Iterable[ResolvedPosition],
    *,
    now: datetime,
    lookback_days: int,
) -> date:
    floor = now.date() - timedelta(days=lookback_days)
    starts = [floor]
    for position in positions:
        if position.opened_at is not None:
            starts.append(position.opened_at.date() - timedelta(days=HISTORY_WARMUP_DAYS))
        for lot in position.lots:
            starts.append(lot.entry_time.date() - timedelta(days=HISTORY_WARMUP_DAYS))
    return min(starts)


def llm_daily_bars(bars: Sequence[DailyBar], limit: int = LLM_DAILY_BARS) -> list[DailyBar]:
    return list(bars)[-limit:]


def bar_indicators(bars: Sequence[DailyBar]) -> dict[str, Decimal | None]:
    closes = [bar.close for bar in bars]
    ma5 = sma(closes, 5)
    ma10 = sma(closes, 10)
    ma20 = sma(closes, 20)
    atr14 = atr(bars, 14)
    window = list(bars)[-LLM_DAILY_BARS:]
    high = max((bar.high for bar in window), default=None)
    low = min((bar.low for bar in window), default=None)
    return {
        "MA5": ma5,
        "MA10": ma10,
        "MA20": ma20,
        "ATR14": atr14,
        "high_15d": high,
        "low_15d": low,
    }
