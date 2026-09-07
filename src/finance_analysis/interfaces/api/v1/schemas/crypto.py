"""BTC REST/WebSocket contracts. Decimal JSON values are strings."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class CryptoKlineResponse(BaseModel):
    symbol: Literal["BTCUSDT"] = "BTCUSDT"
    interval: Literal["1m"] = "1m"
    source: Literal["binance"] = "binance"
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
    closed: bool


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


class CryptoStatusResponse(BaseModel):
    symbol: Literal["BTCUSDT"] = "BTCUSDT"
    enabled: bool
    ready: bool = False
    stream_mode: Literal["websocket", "http_fallback"]
    websocket_connected: bool
    last_update_time: datetime | None = None
    last_websocket_message_time: datetime | None = None
    last_error: str | None = None
    latest_candle: CryptoKlineResponse | None = None
    recent_closed: list[CryptoKlineResponse] = Field(default_factory=list)
    strategy_latest_state: CryptoSnapshotResponse | None = None


class CryptoOverviewResponse(BaseModel):
    symbol: Literal["BTCUSDT"] = "BTCUSDT"
    strategy: CryptoSnapshotResponse | None
    state: CryptoStateResponse
    market: CryptoStatusResponse


class CryptoKlinesResponse(BaseModel):
    items: list[CryptoKlineResponse]


class CryptoSignalsResponse(BaseModel):
    items: list[CryptoSnapshotResponse]


class CryptoRealtimeResponse(BaseModel):
    type: Literal["state"] = "state"
    market: CryptoStatusResponse
