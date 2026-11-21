"""Use original candles and exchange boundaries when building model inputs."""

from collections.abc import Iterable
from datetime import date, datetime, timedelta

from finance_analysis.integrations.crypto.binance import from_ms
from finance_analysis.integrations.market_data.realtime_state.models import CandleState, unique_minute_bars
from finance_analysis.market_stream.config import is_regular_trade_session, market_spec, market_trading_date
from finance_analysis.market_stream.session import in_session, session_bounds
from finance_analysis.minute_forecast.models import (
    BTC_SYMBOL, HORIZON, LOOKBACK, MIN_LOOKBACK, ForecastWindow, ObservedBar,
)
from finance_analysis.stocks.markets import MarketType

MINUTE = timedelta(minutes=1)


def millis(at: datetime) -> int:
    return int(at.timestamp() * 1000)


def make_window(symbol: str, timezone: str, bars: list[ObservedBar], now: datetime,
                targets: list[int]) -> ForecastWindow | None:
    anchor = millis(now.replace(second=0, microsecond=0) - MINUTE)
    if targets and len(bars) >= MIN_LOOKBACK and bars[-1].timestamp == anchor:
        return ForecastWindow(symbol=symbol, timezone=timezone, bars=bars[-LOOKBACK:], targets=targets)
    return None


def stock_window(symbol: str, market: MarketType, candles: Iterable[CandleState],
                 now: datetime) -> ForecastWindow | None:
    minute = now.replace(second=0, microsecond=0)
    if not in_session(market, minute) or not in_session(market, minute - MINUTE):
        return None
    targets: list[int] = []
    for step in range(HORIZON):
        target = minute + step * MINUTE
        if not in_session(market, target):
            break
        targets.append(millis(target))
    return _stock_input(symbol, market, candles, minute, targets)


def stock_close_window(symbol: str, market: MarketType, candles: Iterable[CandleState],
                       day: date) -> ForecastWindow | None:
    bounds = session_bounds(market, day)
    if bounds is None:
        return None
    close = bounds[1]
    # These are hypothetical minute steps immediately after the regular close.
    return _stock_input(symbol, market, candles, close, [millis(close + i * MINUTE) for i in range(HORIZON)])


def _stock_input(symbol: str, market: MarketType, candles: Iterable[CandleState], minute: datetime,
                 targets: list[int]) -> ForecastWindow | None:
    day = market_trading_date(minute, market)
    bars = []
    for candle in unique_minute_bars(candle for candle in candles if candle.bar_time < minute)[-LOOKBACK:]:
        if (candle.confirmed and not candle.sampled and not candle.partial and candle.is_valid()
                and market_trading_date(candle.bar_time, market) == day
                and is_regular_trade_session(candle.trade_session) and in_session(market, candle.bar_time)):
            try:
                bars.append(ObservedBar(
                    timestamp=millis(candle.bar_time), open=candle.open, high=candle.high, low=candle.low,
                    close=candle.close, volume=candle.volume, amount=candle.turnover,
                ))
            except ValueError:
                continue
    return make_window(symbol, market_spec(market).timezone.key, bars, minute, targets)


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
    return make_window(BTC_SYMBOL, "UTC", [parsed[key] for key in sorted(parsed)], now,
                       [millis(minute + step * MINUTE) for step in range(HORIZON)])
