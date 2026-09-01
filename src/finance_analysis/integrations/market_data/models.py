"""Canonical requests and results for market-data integrations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Iterable


class Market(StrEnum):
    CN = "CN"
    US = "US"
    HK = "HK"
    SG = "SG"


class Adjustment(StrEnum):
    RAW = "raw"
    FORWARD = "forward"
    BACKWARD = "backward"


def market_from_value(value: Market | str) -> Market:
    try:
        return value if isinstance(value, Market) else Market(str(value).strip().upper())
    except ValueError as exc:
        raise ValueError(f"Unsupported market {value!r}; expected one of {[item.value for item in Market]}") from exc


def adjustment_from_value(value: Adjustment | str) -> Adjustment:
    try:
        return value if isinstance(value, Adjustment) else Adjustment(str(value).strip().lower())
    except ValueError as exc:
        raise ValueError("adjustment must be explicitly set to raw, forward, or backward") from exc


def _symbols(values: Iterable[str]) -> tuple[str, ...]:
    symbols = tuple(dict.fromkeys(str(value).strip().upper() for value in values if str(value).strip()))
    if not symbols:
        raise ValueError("symbols must not be empty")
    return symbols


@dataclass(frozen=True, slots=True)
class DailyBarsRequest:
    symbols: tuple[str, ...]
    start_date: date
    end_date: date
    adjustment: Adjustment = Adjustment.RAW

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", _symbols(self.symbols))
        object.__setattr__(self, "adjustment", adjustment_from_value(self.adjustment))
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")


@dataclass(frozen=True, slots=True)
class MinuteBarsRequest:
    symbols: tuple[str, ...]
    start_time: datetime
    end_time: datetime
    interval: str = "1m"

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", _symbols(self.symbols))
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("minute-bar times must be timezone-aware")
        object.__setattr__(self, "start_time", self.start_time.astimezone(timezone.utc))
        object.__setattr__(self, "end_time", self.end_time.astimezone(timezone.utc))
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        if self.interval not in {"1m", "2m", "3m", "5m", "10m", "15m", "20m", "30m", "45m", "60m"}:
            raise ValueError(f"Unsupported minute interval: {self.interval}")


@dataclass(frozen=True, slots=True)
class QuoteRequest:
    symbols: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", _symbols(self.symbols))


@dataclass(frozen=True, slots=True)
class InstrumentRequest:
    symbols: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", _symbols(self.symbols))


@dataclass(frozen=True, slots=True)
class MarketBar:
    symbol: str
    market: Market
    interval: str
    trade_date: date
    bar_time: datetime | None
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float | None
    currency: str
    adjustment: Adjustment
    provider: str
    amount_estimated: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["market"] = self.market.value
        value["adjustment"] = self.adjustment.value
        return value


@dataclass(slots=True)
class BatchBarResult:
    data: dict[str, list[MarketBar]] = field(default_factory=dict)
    missing_symbols: list[str] = field(default_factory=list)
    failed_symbols: dict[str, str] = field(default_factory=dict)
    providers_used: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MarketQuote:
    symbol: str
    market: Market
    provider: str
    currency: str
    name: str = ""
    price: float | None = None
    change_pct: float | None = None
    change_amount: float | None = None
    volume: int | None = None
    amount: float | None = None
    volume_ratio: float | None = None
    turnover_rate: float | None = None
    amplitude: float | None = None
    open_price: float | None = None
    high: float | None = None
    low: float | None = None
    pre_close: float | None = None
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    total_mv: float | None = None
    circ_mv: float | None = None
    quote_time: datetime | None = None

    @property
    def code(self) -> str:
        return self.symbol

    @property
    def source(self) -> str:
        return self.provider

    def has_basic_data(self) -> bool:
        return self.price is not None and self.price > 0

    def has_volume_data(self) -> bool:
        return self.volume_ratio is not None or self.turnover_rate is not None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["market"] = self.market.value
        value["code"] = self.symbol
        value["source"] = self.provider
        return {key: item for key, item in value.items() if item is not None}


@dataclass(slots=True)
class BatchQuoteResult:
    data: dict[str, MarketQuote] = field(default_factory=dict)
    missing_symbols: list[str] = field(default_factory=list)
    failed_symbols: dict[str, str] = field(default_factory=dict)
    providers_used: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MarketIndex:
    symbol: str
    name: str
    market: Market
    provider: str
    price: float
    change: float = 0.0
    change_pct: float = 0.0
    open: float | None = None
    high: float | None = None
    low: float | None = None
    pre_close: float | None = None
    volume: int | None = None
    amount: float | None = None
    amplitude: float | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.update({"market": self.market.value, "code": self.symbol, "current": self.price})
        return value


@dataclass(frozen=True, slots=True)
class MarketStats:
    market: Market
    provider: str
    up_count: int
    down_count: int
    flat_count: int
    limit_up_count: int = 0
    limit_down_count: int = 0
    total_amount: float | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["market"] = self.market.value
        return value


@dataclass(frozen=True, slots=True)
class SectorRankings:
    market: Market
    provider: str
    top: list[dict[str, Any]]
    bottom: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class InstrumentInfo:
    symbol: str
    market: Market
    name: str
    provider: str
    currency: str
    exchange: str | None = None
    instrument_type: str | None = None
    lot_size: int | None = None


@dataclass(slots=True)
class BatchInstrumentResult:
    data: dict[str, InstrumentInfo] = field(default_factory=dict)
    missing_symbols: list[str] = field(default_factory=list)
    failed_symbols: dict[str, str] = field(default_factory=dict)
    providers_used: dict[str, str] = field(default_factory=dict)
