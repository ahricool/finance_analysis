"""Validated domain values. Candle close_time is the exclusive UTC boundary."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class Kline:
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    trade_count: int
    taker_buy_volume: Decimal
    taker_buy_quote_volume: Decimal
    closed: bool = True
    symbol: str = "BTCUSDT"
    interval: str = "1m"
    source: str = "binance"

    def __post_init__(self):
        if self.symbol != "BTCUSDT" or self.interval != "1m" or self.source != "binance":
            raise ValueError("Only Binance BTCUSDT 1m candles are accepted")
        for timestamp in (self.open_time, self.close_time):
            if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
                raise ValueError("Kline timestamps must be aware UTC")
        if self.open_time.second or self.open_time.microsecond:
            raise ValueError("Kline must start at a UTC minute boundary")
        if self.close_time != self.open_time + timedelta(minutes=1):
            raise ValueError("Kline must cover exactly one minute")
        for name in (
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "taker_buy_volume",
            "taker_buy_quote_volume",
        ):
            value = getattr(self, name)
            if not value.is_finite() or value < 0:
                raise ValueError(f"Invalid {name}")
        if not (0 < self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high):
            raise ValueError("Invalid OHLC range")
        if (
            self.trade_count < 0
            or self.taker_buy_volume > self.volume
            or self.taker_buy_quote_volume > self.quote_volume
        ):
            raise ValueError("Invalid volume/trade count")

    def storage_values(self):
        values = asdict(self)
        values.pop("closed")
        return values


@dataclass(frozen=True)
class Bar:
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class StrategyState:
    symbol: str = "BTCUSDT"
    position_state: Literal["FLAT", "LONG"] = "FLAT"
    entry_price: Decimal | None = None
    entry_time: datetime | None = None
    highest_price_since_entry: Decimal | None = None
    initial_stop: Decimal | None = None
    trailing_stop: Decimal | None = None
    updated_at: datetime | None = None
