"""BTC strategy REST contracts. Decimal JSON values are strings."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class CryptoStateResponse(BaseModel):
    symbol: Literal["BTCUSDT"] = "BTCUSDT"
    position_state: Literal["FLAT", "LONG"]
    entry_price: Decimal | None = None
    entry_time: datetime | None = None
    highest_price_since_entry: Decimal | None = None
    initial_stop: Decimal | None = None
    trailing_stop: Decimal | None = None
    updated_at: datetime | None = None


class CryptoSnapshotResponse(BaseModel):
    symbol: Literal["BTCUSDT"] = "BTCUSDT"
    evaluated_at: datetime
    regime: Literal["BULL", "BEAR", "RANGE", "UNKNOWN"]
    setup: Literal["BREAKOUT", "NONE"]
    action: Literal["BUY", "WAIT", "HOLD", "EXIT"]
    price: Decimal
    ema20_1h: Decimal | None = None
    ema50_1h: Decimal | None = None
    ema20_15m: Decimal | None = None
    breakout_level_15m: Decimal | None = None
    volume_ratio_15m: Decimal | None = None
    atr14_15m: Decimal | None = None
    initial_stop: Decimal | None = None
    trailing_stop: Decimal | None = None
    position_state: Literal["FLAT", "LONG"]
    reason: str


class CryptoOverviewResponse(BaseModel):
    symbol: Literal["BTCUSDT"] = "BTCUSDT"
    strategy: CryptoSnapshotResponse | None
    state: CryptoStateResponse


class CryptoSignalsResponse(BaseModel):
    items: list[CryptoSnapshotResponse]
