"""Versioned payloads shared by the live publisher and its read-only API."""

from pydantic import BaseModel, Field, FiniteFloat, model_validator

PROTOCOL = 1
MINUTE_MS = 60_000
LOOKBACK = 240
MIN_LOOKBACK = 30
HORIZON = 5
BATCH_SIZE = 10
BTC_SYMBOL = "BTCUSDT"


class Prices(BaseModel):
    open: FiniteFloat = Field(gt=0)
    high: FiniteFloat = Field(gt=0)
    low: FiniteFloat = Field(gt=0)
    close: FiniteFloat = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self):
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("invalid OHLC range")
        return self


class ObservedBar(Prices):
    timestamp: int
    volume: FiniteFloat = Field(ge=0)
    amount: FiniteFloat | None = Field(default=None, ge=0)


class PredictedBar(Prices):
    timestamp: int


class ForecastWindow(BaseModel):
    symbol: str
    timezone: str
    bars: list[ObservedBar]
    targets: list[int]


class Prediction(BaseModel):
    symbol: str
    bars: list[PredictedBar] = Field(min_length=1, max_length=HORIZON)


class InferenceResult(BaseModel):
    protocol: int
    model: str = Field(min_length=1, max_length=20)
    weights_revision: str = Field(min_length=1, max_length=128)
    predictions: list[Prediction] = Field(max_length=BATCH_SIZE)


class ForecastSnapshot(BaseModel):
    model: str
    weights_revision: str
    symbol: str
    anchor: int
    anchor_close: FiniteFloat = Field(gt=0)
    generated_at: int
    lookback: int
    bars: list[PredictedBar] = Field(min_length=1, max_length=HORIZON)


class MinuteForecastResponse(BaseModel):
    enabled: bool
    forecast: ForecastSnapshot | None = None
    comparison: ForecastSnapshot | None = None
