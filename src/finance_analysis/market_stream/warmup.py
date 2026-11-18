"""Historical 1-minute bar loading and deterministic realtime merge rules."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import chain
from typing import Iterable

from finance_analysis.integrations.market_data import MarketDataService
from finance_analysis.integrations.market_data.config import provider_order
from finance_analysis.integrations.market_data.registry import MINUTE_BARS
from finance_analysis.integrations.market_data.realtime_state.models import CandleState, unique_minute_bars
from finance_analysis.market_stream.config import is_regular_session_minute, latest_completed_bar_time, market_trading_date
from finance_analysis.stocks.markets import MarketType


def warmup_bar_starts(now: datetime, market_type: MarketType) -> list[datetime]:
    """All closed regular minutes of the displayed trading day."""
    from finance_analysis.market_stream.session import display_day, session_bounds

    start, close = session_bounds(market_type, display_day(market_type, now))
    cursor = min(now.replace(second=0, microsecond=0), close) - timedelta(minutes=1)
    expected = []
    while cursor >= start:
        if is_regular_session_minute(cursor, market_type):
            expected.append(cursor)
        cursor -= timedelta(minutes=1)
    return list(reversed(expected))


def _history_bar_is_confirmed(
    bar_time: datetime,
    *,
    received_at: datetime,
    market_type: MarketType,
    expected_completed: datetime | None,
) -> bool:
    bar_date = market_trading_date(bar_time, market_type)
    received_date = market_trading_date(received_at, market_type)
    if bar_date < received_date:
        return True
    return bar_date == received_date and expected_completed is not None and bar_time <= expected_completed


class LongbridgeHistoryLoader:
    def __init__(self, market_data_service: MarketDataService | None = None) -> None:
        self.market_data = market_data_service or MarketDataService()

    async def fetch(self, symbol: str, market_type: MarketType, count: int) -> list[CandleState]:
        requested_at = datetime.now(timezone.utc)
        from finance_analysis.market_stream.session import display_day, session_bounds

        day = display_day(market_type, requested_at)
        start, close = session_bounds(market_type, day)
        end = min(requested_at, close)
        result = await asyncio.to_thread(
            self.market_data.get_minute_bars,
            [symbol],
            start,
            end,
            interval="1m",
            providers=tuple(name for name in provider_order(market_type, MINUTE_BARS) if name != "streaming"),
            required_bar_starts=warmup_bar_starts(requested_at, market_type),
        )
        received_at = datetime.now(timezone.utc)
        values = result.data.get(symbol)
        if not values:
            raise RuntimeError(result.failed_symbols.get(symbol) or f"No minute history returned for {symbol}")
        expected_completed = latest_completed_bar_time(requested_at, market_type)
        bars: list[CandleState] = []
        for value in values:
            bar_time = value.bar_start or value.bar_time
            if bar_time is None or bar_time > requested_at:
                continue
            bar = CandleState(
                symbol=symbol,
                bar_time=bar_time,
                open=Decimal(str(value.open)),
                high=Decimal(str(value.high)),
                low=Decimal(str(value.low)),
                close=Decimal(str(value.close)),
                volume=value.volume,
                turnover=Decimal(str(value.amount)) if value.amount is not None else None,
                trade_session=None,
                confirmed=_history_bar_is_confirmed(
                    bar_time, received_at=requested_at, market_type=market_type, expected_completed=expected_completed,
                ),
                received_at=received_at,
                source=value.provider,
            )
            if bar.is_valid():
                bars.append(bar)
        return sorted(bars, key=lambda item: item.bar_time)


def merge_warmup_bars(
    historical: Iterable[CandleState],
    realtime: Iterable[CandleState],
    *,
    limit: int,
) -> list[CandleState]:
    """Merge by minute while preserving confirmed history and live current bars."""
    live = unique_minute_bars(bar for bar in realtime if bar.is_valid())
    history = (bar for bar in historical if bar.is_valid())
    merged = unique_minute_bars(chain(history, live))
    # An open minute can change while the history request is in flight.
    if live and not merged[-1].confirmed and live[-1].bar_time == merged[-1].bar_time:
        merged[-1] = live[-1]
    return merged[-max(1, limit):]
