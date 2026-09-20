"""Validated domain values. Candle close_time is the exclusive UTC boundary."""

from dataclasses import dataclass
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
    interval: str = "15m"
    source: str = "binance"

    def __post_init__(self):
        if self.symbol != "BTCUSDT" or self.interval not in ("15m", "1h") or self.source != "binance":
            raise ValueError("Only Binance BTCUSDT 15m/1h candles are accepted")
        for timestamp in (self.open_time, self.close_time):
            if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
                raise ValueError("Kline timestamps must be aware UTC")
        minutes = 15 if self.interval == "15m" else 60
        if self.open_time.minute % minutes or self.open_time.second or self.open_time.microsecond:
            raise ValueError("Kline must start at a UTC minute boundary")
        if self.close_time != self.open_time + timedelta(minutes=minutes):
            raise ValueError("Kline duration must match interval")
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


@dataclass(frozen=True)
class StrategyState:
    strategy_key: str = "btc_breakout_v1"
    symbol: str = "BTCUSDT"
    position_state: Literal["FLAT", "LONG"] = "FLAT"
    position_pct: Decimal | None = None
    average_entry_price: Decimal | None = None
    entry_price: Decimal | None = None
    entry_time: datetime | None = None
    highest_price_since_entry: Decimal | None = None
    initial_stop: Decimal | None = None
    trailing_stop: Decimal | None = None
    updated_at: datetime | None = None

    def __post_init__(self):
        pct = self.position_pct
        if pct is None:
            pct = Decimal(1) if self.position_state == "LONG" else Decimal(0)
        if not pct.is_finite() or not Decimal(0) <= pct <= Decimal(1):
            raise ValueError("Position must be between zero and one")
        average = (self.average_entry_price or self.entry_price) if pct > 0 else None
        object.__setattr__(self, "position_pct", pct)
        object.__setattr__(self, "position_state", "LONG" if pct > 0 else "FLAT")
        object.__setattr__(self, "average_entry_price", average)
        object.__setattr__(self, "entry_price", average)
