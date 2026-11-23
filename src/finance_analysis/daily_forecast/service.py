"""Forecast upcoming exchange sessions from the synchronized daily close."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time
from itertools import batched
from time import monotonic, sleep
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from finance_analysis.core.time import utc_now
from finance_analysis.daily_forecast.models import DailyForecast, DailyForecastBar
from finance_analysis.database.repositories.daily_forecast import DailyForecastRepository
from finance_analysis.market_review.trading_calendar import MARKET_TIMEZONE, get_upcoming_trading_days
from finance_analysis.minute_forecast.models import (
    BATCH_SIZE, HORIZON, LOOKBACK, MIN_LOOKBACK, PROTOCOL, ForecastWindow, InferenceResult, ObservedBar,
)

HISTORY_BATCH_SIZE = 100


def _timestamp(day: date, zone: ZoneInfo) -> int:
    return int(datetime.combine(day, time.min, zone).timestamp() * 1000)


def _windows(histories, as_of: date, zone: ZoneInfo, targets: list[int]) -> list[ForecastWindow]:
    windows = []
    for symbol, rows in histories.items():
        if len(rows) < MIN_LOOKBACK or rows[-1].date != as_of:
            continue
        try:
            bars = [
                ObservedBar(
                    timestamp=_timestamp(row.date, zone), open=row.open, high=row.high,
                    low=row.low, close=row.close, volume=row.volume, amount=row.amount,
                )
                for row in rows
            ]
        except ValidationError:
            continue
        windows.append(ForecastWindow(symbol=symbol, timezone=zone.key, bars=bars, targets=targets))
    return windows


def _infer(client: httpx.Client, windows: Sequence[ForecastWindow], model: str) -> InferenceResult:
    deadline = monotonic() + 30
    payload = {"protocol": PROTOCOL, "interval": "1d", "windows": [window.model_dump() for window in windows]}
    while True:
        response = client.post("/predict", json=payload)
        if response.status_code != 503 or monotonic() >= deadline:
            response.raise_for_status()
            break
        sleep(1)
    result = InferenceResult.model_validate_json(response.content)
    if result.protocol != PROTOCOL or result.model != model:
        raise ValueError("Kronos returned an incompatible protocol or model")
    return result


def run_daily_forecast(
    market: str,
    as_of: date,
    instrument_ids: Sequence[int],
    url: str,
    model: str,
    repository: DailyForecastRepository,
) -> dict:
    """Publish a complete market replacement after all transport batches finish."""
    zone = ZoneInfo(MARKET_TIMEZONE[market.lower()])
    days = get_upcoming_trading_days(market.lower(), as_of, HORIZON)
    if not days:
        raise ValueError(f"{market} exchange calendar did not provide upcoming forecast sessions")
    targets = [_timestamp(day, zone) for day in days]
    forecasts = []
    eligible = 0
    revision = None
    with httpx.Client(base_url=url, timeout=30, trust_env=False) as client:
        for ids in batched(instrument_ids, HISTORY_BATCH_SIZE):
            windows = _windows(repository.histories(market, ids, as_of, LOOKBACK), as_of, zone, targets)
            eligible += len(windows)
            groups = defaultdict(list)
            for window in windows:
                groups[len(window.bars)].append(window)
            for group in groups.values():
                for batch in batched(group, BATCH_SIZE):
                    result = _infer(client, batch, model)
                    if revision is not None and revision != result.weights_revision:
                        raise ValueError("Kronos weights changed during daily inference")
                    revision = result.weights_revision
                    generated_at = utc_now()
                    by_symbol = {window.symbol: window for window in batch}
                    for prediction in result.predictions:
                        window = by_symbol.pop(prediction.symbol, None)
                        if window is None or [bar.timestamp for bar in prediction.bars] != targets:
                            raise ValueError("Kronos returned an unexpected daily symbol or timestamp")
                        forecasts.append(DailyForecast(
                            symbol=window.symbol, anchor_date=as_of, anchor_close=window.bars[-1].close,
                            generated_at=generated_at, model=model, weights_revision=revision, lookback=len(window.bars),
                            bars=[
                                DailyForecastBar(trade_date=day, **bar.model_dump(exclude={"timestamp"}))
                                for day, bar in zip(days, prediction.bars, strict=True)
                            ],
                        ))
                    # Leave a gap between GPU batches for live minute requests.
                    sleep(0.2)
    if eligible and not forecasts:
        raise ValueError("Kronos returned no usable daily forecasts")
    published = repository.replace_market(market, as_of, forecasts)
    return {
        "market": market, "trade_date": as_of.isoformat(), "scope_symbols": len(instrument_ids),
        "eligible_symbols": eligible, "predicted_symbols": len(forecasts), "horizon": len(days), "published": published,
    }
