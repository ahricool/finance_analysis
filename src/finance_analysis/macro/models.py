"""Typed inputs and results for pure macro calculations."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat

Trend = Literal["UP", "DOWN", "NEUTRAL"]
Regime = Literal["RISK_ON", "NEUTRAL", "RISK_OFF"]
SeriesRange = Literal["20d", "60d", "120d", "250d", "ytd"]
SeriesMode = Literal["price", "normalized", "relative"]


@dataclass(frozen=True)
class MacroContext:
    names: dict[str, str]
    latest_dates: dict[str, date]
    trade_date: date | None
    start_date: date | None


class DataQuality(BaseModel):
    expected: int
    available: int
    coverage: float = Field(ge=0, le=1)
    missing_symbols: list[str]
    stale_symbols: list[str]
    insufficient_history_symbols: list[str] = Field(default_factory=list)
    partial: bool


class Metrics(BaseModel):
    trade_date: date | None = None
    ret_1d: FiniteFloat | None = None
    ret_5d: FiniteFloat | None = None
    ret_20d: FiniteFloat | None = None
    trend: Trend | None = None


class InstrumentMetrics(Metrics):
    code: str
    name: str
    category: str
    close: FiniteFloat | None


class RatioMetrics(Metrics):
    key: str
    name: str
    value: FiniteFloat | None
    signal: Regime | None
    partial: bool


class RiskSignal(BaseModel):
    key: str
    risk_on_trend: Trend
    trend: Trend | None
    weight: int
    contribution: float | None


class MacroStates(BaseModel):
    rates: Literal["EASING", "PRESSURE", "NEUTRAL"] | None
    credit: Literal["HEALTHY", "WEAK", "NEUTRAL"] | None
    dollar: Literal["STRONG", "WEAK", "NEUTRAL"] | None
    volatility: Literal["ELEVATED", "CALM", "NEUTRAL"] | None


class MacroDashboard(BaseModel):
    trade_date: date | None
    generated_at: datetime
    regime: Regime | None
    risk_score: float | None = Field(ge=0, le=100)
    signal_coverage: float = Field(ge=0, le=1)
    signals: list[RiskSignal]
    states: MacroStates
    instruments: list[InstrumentMetrics]
    ratios: list[RatioMetrics]
    data_quality: DataQuality


class SeriesPoint(BaseModel):
    date: date
    value: FiniteFloat


class MacroSeries(BaseModel):
    key: str
    code: str | None = None
    name: str
    category: str
    points: list[SeriesPoint]
    partial: bool


class MacroSeriesResult(BaseModel):
    range: SeriesRange
    mode: SeriesMode
    benchmark: str | None
    trade_date: date | None
    series: list[MacroSeries]
    data_quality: DataQuality
