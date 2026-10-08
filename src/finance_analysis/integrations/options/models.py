"""One observation is always one provider/feed; never merge quote or IV legs."""

from datetime import date, datetime
from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict, field_validator


class OptionObservation(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    symbol: str
    underlying_symbol: str
    option_type: Literal["call", "put"]
    expiration: date
    strike: float
    multiplier: float | None = None
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    last_price: float | None = None
    last_trade_time: datetime | None = None
    volume: float | None = None
    volume_date: date | None = None
    traded_price: float | None = None
    traded_price_method: str | None = None
    open_interest: float | None = None
    oi_date: date | None = None
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    underlying_price: float | None = None
    underlying_timestamp: datetime | None = None
    quote_timestamp: datetime | None = None
    iv_timestamp: datetime | None = None
    observed_at: datetime
    data_source: str
    feed_type: Literal["delayed", "indicative", "opra"]
    limitations: list[str] = []

    @field_validator("last_trade_time", "underlying_timestamp", "quote_timestamp", "iv_timestamp", "observed_at")
    @classmethod
    def aware_times(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Option times must be timezone-aware")
        return value


class OptionChain(BaseModel):
    symbol: str
    observed_at: datetime
    observations: list[OptionObservation] = []
    errors: list[str] = []
    coverage: dict = {}


class OptionsProvider(Protocol):
    def fetch(self, symbol: str, now: datetime, session_date: date, config) -> OptionChain: ...
