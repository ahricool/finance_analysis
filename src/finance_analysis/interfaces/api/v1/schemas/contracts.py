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
    funding_timestamp: int | None = None
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


class ContractFavoriteUpdate(BaseModel):
    enabled: bool


class ContractStructure(BaseModel):
    kind: str
    phase: str
    reference: bool


class ContractAnalysis(BaseModel):
    trend_1m: dict | None = None
    pattern_1m: dict | None = None
    structure: ContractStructure | None = None
    as_of: int
    score: float | None
    direction: str | None
    state: str | None
    reference: bool
    opportunity: ContractOpportunity | None
    windows: dict[str, ContractWindow]


class AccountRatio(BaseModel):
    source_time: int
    long: float
    short: float
    ratio: float | None


class OpenInterest(BaseModel):
    source_time: int
    quantity: float
    usdt: float


class TakerVolume(BaseModel):
    source_time: int
    buy: float
    sell: float
    ratio: float | None


class MetricValues(BaseModel):
    timestamp: int
    accounts: AccountRatio | None
    top_accounts: AccountRatio | None
    top_positions: AccountRatio | None
    oi: OpenInterest | None
    taker: TakerVolume | None


class HourSummary(MetricValues):
    price_change: float | None
    oi_change: float | None
    buy_share: float | None
    status: dict[str, str]


class PriceBoundary(BaseModel):
    source_time: int
    source: str
    open: float
    close: float


class HistoricalSample(MetricValues):
    symbol: str
    period: str
    price: PriceBoundary | None


class HistoryPage(BaseModel):
    items: list[HistoricalSample]
    next_start: int | None


class MarkPrice(BaseModel):
    timestamp: int
    mark_price: float | None
    index_price: float | None
    basis: float | None
    next_funding: int | None
    funding_rate: float


class BookTicker(BaseModel):
    timestamp: int
    bid: float
    ask: float
    spread_bps: float


class DepthSnapshot(BaseModel):
    timestamp: int
    bids: float | None
    asks: float | None
    bids_levels: int
    asks_levels: int


class ContractQuote(Contract):
    quote: Quote | None
    mark: MarkPrice | None = None
    book: BookTicker | None = None
    metrics: HourSummary | None = None
    analysis: ContractAnalysis | None = None


class Candle(BaseModel):
    closed: bool | None = None
    received_at_ms: int | None = None
    event_time: int | None = None
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
