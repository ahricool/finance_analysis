"""Contract market API wire contracts."""
from pydantic import BaseModel, Field


class ContractCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")
    category: str | None = Field(default=None, max_length=32)


class Contract(BaseModel):
    symbol: str
    category: str
    underlying_symbol: str | None = None


class Quote(BaseModel):
    price: float
    change_pct: float
    turnover: float
    funding_rate: float | None
    timestamp: int


class ContractWindow(BaseModel):
    score: float | None
    direction: int | None
    returnPct: float | None
    dataStatus: str
    availableBars: int
    missingBars: int


class ContractOpportunity(BaseModel):
    kind: str
    direction: str
    quality_score: float


class ContractAnalysis(BaseModel):
    as_of: int
    score: float | None
    direction: str | None
    state: str | None
    reference: bool
    opportunity: ContractOpportunity | None
    windows: dict[str, ContractWindow]


class ContractQuote(Contract):
    quote: Quote | None
    analysis: ContractAnalysis | None = None


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
