"""Contract market API wire contracts."""
from pydantic import BaseModel, Field


class ContractCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")
    category: str | None = Field(default=None, max_length=32)


class Contract(BaseModel):
    symbol: str
    category: str


class Quote(BaseModel):
    price: float
    change_pct: float
    turnover: float
    funding_rate: float | None
    timestamp: int


class ContractQuote(Contract):
    quote: Quote | None


class Candle(BaseModel):
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float


class MarketSnapshot(BaseModel):
    items: list[ContractQuote]
    symbol: str | None
    minutes: list[Candle] | None
    daily_current: Candle | None
