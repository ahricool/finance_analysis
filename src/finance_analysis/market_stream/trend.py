"""Pure 1-minute rolling moving-average trend calculation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from finance_analysis.core.time import utc_now
from finance_analysis.integrations.market_data.realtime_state.models import CandleState, TrendDirection, TrendState
from finance_analysis.market_stream.config import (
    is_regular_session_minute,
    is_regular_trade_session,
    latest_completed_bar_time,
    market_trading_date,
)
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

    target_date = market_trading_date(current, market_type)
    latest_completed = latest_completed_bar_time(current, market_type)
    symbol = next((bar.symbol for bar in bars), "")
    candidates: dict[tuple[datetime, str], CandleState] = {}
    if latest_completed is not None:
        for bar in bars:
            if (
                not bar.confirmed
                or not bar.is_valid()
                or bar.bar_time.tzinfo is None
                or bar.bar_time.utcoffset() is None
                or bar.bar_time > latest_completed
                or market_trading_date(bar.bar_time, market_type) != target_date
                or not is_regular_session_minute(bar.bar_time, market_type)
                or not is_regular_trade_session(bar.trade_session)
            ):
                continue
            previous = candidates.get(bar.identity)
            if previous is None or (bar.confirmed, bar.received_at) >= (
                previous.confirmed,
                previous.received_at,
            ):
                candidates[bar.identity] = bar

    ordered = sorted(candidates.values(), key=lambda bar: (bar.bar_time, bar.trade_session or ""))
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
    if count < minimum_period:
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
