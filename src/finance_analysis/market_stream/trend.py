"""Pure 1-minute rolling moving-average trend calculation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal

from finance_analysis.core.time import utc_now
from finance_analysis.integrations.market_data.realtime_state.models import CandleState, TrendDirection, TrendState
from finance_analysis.market_stream.config import market_trading_date
from finance_analysis.market_stream.patterns.features import sanitize_bars
from finance_analysis.stocks.markets import MarketType


def calculate_ma_trend(
    bars: Sequence[CandleState],
    *,
    market_type: MarketType,
    target_period: int = 20,
    minimum_period: int = 5,
    as_of: datetime | None = None,
) -> TrendState:
    """Calculate the latest trend using each completed bar's contemporaneous rolling mean."""
    if target_period < 1 or minimum_period < 1 or minimum_period > target_period:
        raise ValueError("periods must satisfy 1 <= minimum_period <= target_period")
    current = as_of or utc_now()
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    ordered = sanitize_bars([bar for bar in bars if bar.bar_time.utcoffset() is not None and bar.bar_time + timedelta(minutes=1) <= current], market_type)
    target_date = market_trading_date(ordered[-1].bar_time if ordered else current, market_type)
    symbol = ordered[-1].symbol if ordered else next((bar.symbol for bar in bars), "")
    return rolling_ma_trend(ordered, symbol, target_date, target_period, minimum_period)


def rolling_ma_trend(
    ordered: Sequence[CandleState], symbol: str, target_date: date, target_period: int = 20, minimum_period: int = 5,
) -> TrendState:
    """Evaluate a validated, contiguous sequence of completed session bars."""
    latest = ordered[-1] if ordered else None
    count = len(ordered)
    base = TrendState(
        symbol=latest.symbol if latest else symbol,
        target_period=target_period,
        effective_period=min(count, target_period),
        minimum_period=minimum_period,
        close=latest.close if latest else None,
        bar_time=latest.bar_time if latest else None,
        trading_date=target_date if latest else None,
        trade_session=latest.trade_session if latest else None,
    )
    if not count:
        return base
    if count < minimum_period:
        base.ma_value = sum((bar.close for bar in ordered), Decimal("0")) / count
        base.distance_pct = (latest.close / base.ma_value - 1) * 100
        return base

    directions: list[TrendDirection] = []
    latest_ma: Decimal | None = None
    for index in range(minimum_period - 1, count):
        window_start = max(0, index - target_period + 1)
        window = ordered[window_start : index + 1]
        ma_value = sum((bar.close for bar in window), Decimal("0")) / Decimal(len(window))
        close = ordered[index].close
        direction: TrendDirection = "above" if close > ma_value else "below" if close < ma_value else "neutral"
        directions.append(direction)
        latest_ma = ma_value

    state = directions[-1]
    streak = 0
    for direction in reversed(directions):
        if direction != state:
            break
        streak += 1
    assert latest is not None and latest_ma is not None
    return TrendState(
        symbol=latest.symbol,
        target_period=target_period,
        effective_period=min(count, target_period),
        minimum_period=minimum_period,
        state=state,
        streak=streak,
        ma_value=latest_ma,
        close=latest.close,
        distance_pct=(latest.close / latest_ma - Decimal("1")) * Decimal("100"),
        bar_time=latest.bar_time,
        trading_date=target_date,
        trade_session=latest.trade_session,
        confirmed=True,
    )
