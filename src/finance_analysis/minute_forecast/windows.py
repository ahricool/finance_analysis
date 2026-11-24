"""Use original candles and exchange boundaries when building model inputs."""

from bisect import bisect_left
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from functools import lru_cache

from finance_analysis.integrations.crypto.binance import from_ms
from finance_analysis.integrations.market_data.realtime_state.models import CandleState, unique_minute_bars
from finance_analysis.market_stream.config import is_regular_trade_session, market_spec, market_trading_date
from finance_analysis.market_stream.session import session_bounds
from finance_analysis.minute_forecast.models import (
    BTC_HORIZON, BTC_SYMBOL, CLOSE_REPLAY_HORIZON, LOOKBACK, MAX_SESSION_MINUTES, MIN_LOOKBACK, MINUTE_MS,
    ForecastWindow, ObservedBar,
)
from finance_analysis.stocks.markets import MarketType

MINUTE = timedelta(minutes=1)


def millis(at: datetime) -> int:
    return int(at.timestamp() * 1000)


def make_window(symbol: str, timezone: str, bars: list[ObservedBar], anchor: int,
                targets: list[int]) -> ForecastWindow | None:
    if targets and len(bars) >= MIN_LOOKBACK and bars[-1].timestamp == anchor:
        return ForecastWindow(symbol=symbol, timezone=timezone, bars=bars, targets=targets)
    return None


@lru_cache(maxsize=32)
def _session_minutes(market: MarketType, day: date) -> tuple[int, ...]:
    bounds = session_bounds(market, day)
    if bounds is None:
        return ()
    spec = market_spec(market)
    minutes = []
    for opened, closed in spec.regular_sessions:
        start = max(bounds[0], datetime.combine(day, opened, spec.timezone))
        end = min(bounds[1], datetime.combine(day, closed, spec.timezone))
        minutes.extend(range(millis(start), millis(end), MINUTE_MS))
    return tuple(minutes)


def stock_window(symbol: str, market: MarketType, candles: Iterable[CandleState],
                 now: datetime) -> ForecastWindow | None:
    minute = millis(now.replace(second=0, microsecond=0))
    session = _session_minutes(market, market_trading_date(now, market))
    split = bisect_left(session, minute)
    if not MIN_LOOKBACK <= split < len(session) <= MAX_SESSION_MINUTES or session[split] != minute:
        return None
    expected = session[:split]
    bars = _stock_bars(candles, expected)
    if len(bars) != len(expected):
        return None  # A data gap must be repaired by the feed before using a full session window.
    return make_window(symbol, market_spec(market).timezone.key, bars, expected[-1], list(session[split:]))


def stock_close_window(symbol: str, market: MarketType, candles: Iterable[CandleState],
                       day: date) -> ForecastWindow | None:
    session = _session_minutes(market, day)
    if not session:
        return None
    bars = _stock_bars(candles, session[-LOOKBACK:])
    # These are hypothetical minute steps immediately after the regular close.
    targets = [session[-1] + step * MINUTE_MS for step in range(1, CLOSE_REPLAY_HORIZON + 1)]
    return make_window(symbol, market_spec(market).timezone.key, bars, session[-1], targets)


def _stock_bars(candles: Iterable[CandleState], expected: tuple[int, ...]) -> list[ObservedBar]:
    eligible = set(expected)
    bars = []
    for candle in unique_minute_bars(candles):
        timestamp = millis(candle.bar_time)
        if (timestamp in eligible and candle.confirmed and not candle.sampled and not candle.partial
                and candle.is_valid() and is_regular_trade_session(candle.trade_session)):
            try:
                bars.append(ObservedBar(
                    timestamp=timestamp, open=candle.open, high=candle.high, low=candle.low,
                    close=candle.close, volume=candle.volume, amount=candle.turnover,
                ))
            except ValueError:
                continue
    return bars


def btc_window(rows: list, now: datetime) -> ForecastWindow | None:
    minute = now.replace(second=0, microsecond=0)
    parsed = {}
    for row in rows:
        try:
            opened = from_ms(row[0])
            closed = from_ms(int(row[6]) + 1)
            if opened.second or opened.microsecond or closed != opened + MINUTE or closed > minute:
                continue
            bar = ObservedBar(timestamp=millis(opened), open=row[1], high=row[2], low=row[3], close=row[4],
                              volume=row[5], amount=row[7])
        except (IndexError, KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        parsed[bar.timestamp] = bar
    anchor = millis(minute) - MINUTE_MS
    return make_window(BTC_SYMBOL, "UTC", [parsed[key] for key in sorted(parsed)[-LOOKBACK:]], anchor,
                       [millis(minute + step * MINUTE) for step in range(BTC_HORIZON)])
