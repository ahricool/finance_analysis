"""Settle live forecasts against confirmed candles and cache per-day errors."""

from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone

from finance_analysis.integrations.market_data.realtime_state.models import CandleState, unique_minute_bars
from finance_analysis.market_stream.config import is_regular_trade_session, market_trading_date
from finance_analysis.minute_forecast.cache import EVALUATION_TTL_SECONDS, forecast_key, pending_error_key
from finance_analysis.minute_forecast.models import (
    ERROR_HORIZON, MINUTE_MS, AverageError, ForecastAccuracy, ForecastError, ForecastSnapshot,
    RecentErrors,
)
from finance_analysis.minute_forecast.windows import millis
from finance_analysis.stocks.markets import MarketType

# A provider can confirm the final minute late. Wait briefly before settling
# an incomplete batch, then count only the targets with real candles.
CONFIRMATION_GRACE_MS = 2 * MINUTE_MS

_SETTLE = """
if redis.call('ZREM', KEYS[1], ARGV[1]) == 0 then return 0 end
local report = cjson.decode(ARGV[2])
if #report.rows == 0 then return 1 end
for _, row in ipairs(report.rows) do
    redis.call('HINCRBY', KEYS[2], 'count:' .. row.step, 1)
    redis.call('HINCRBYFLOAT', KEYS[2], 'error:' .. row.step, row.error)
    redis.call('HINCRBYFLOAT', KEYS[2], 'baseline:' .. row.step, row.baseline_error)
end
redis.call('EXPIRE', KEYS[2], ARGV[3])
local previous = redis.call('HGET', KEYS[3], 'issued_at')
if not previous or tonumber(previous) < report.issued_at then
    redis.call('HSET', KEYS[3], 'issued_at', report.issued_at, 'report', ARGV[2], 'forecast', ARGV[1])
    redis.call('EXPIRE', KEYS[3], ARGV[3])
end
return 1
"""


def evaluation_day(now: datetime, market: MarketType | None) -> date:
    return market_trading_date(now, market) if market else now.astimezone(timezone.utc).date()


def _accuracy_key(symbol: str, model: str) -> str:
    return f"{forecast_key(symbol)}:accuracy:{model}"


def _score(forecast: ForecastSnapshot, closes: Mapping[int, float]) -> RecentErrors:
    return RecentErrors(issued_at=forecast.bars[0].timestamp, rows=[
        ForecastError(
            step=step, close=closes[bar.timestamp], error=abs(bar.close - closes[bar.timestamp]),
            baseline_error=abs(forecast.anchor_close - closes[bar.timestamp]),
        )
        for step, bar in enumerate(forecast.bars, start=1) if bar.timestamp in closes
    ])


async def settle_forecasts(
    redis, bars: Mapping[str, Iterable[CandleState]], markets: Mapping[str, MarketType],
    now: datetime,
) -> None:
    symbols = [symbol for symbol in markets if bars.get(symbol)]
    if not symbols:
        return
    now_ms = millis(now)
    reads = redis.pipeline(transaction=False)
    for symbol in symbols:
        reads.zrangebyscore(pending_error_key(symbol), "-inf", now_ms)
    candidates = await reads.execute()

    writes = redis.pipeline(transaction=False)
    for symbol, pending in zip(symbols, candidates, strict=True):
        if not pending:
            continue
        closes = {
            millis(bar.bar_time): float(bar.close) for bar in unique_minute_bars(bars[symbol])
            if bar.confirmed and not bar.sampled and not bar.partial and bar.is_valid()
            and is_regular_trade_session(bar.trade_session)
        }
        for raw in pending:
            forecast = ForecastSnapshot.model_validate_json(raw)
            recent = _score(forecast, closes)
            expiry = forecast.bars[-1].timestamp + MINUTE_MS + CONFIRMATION_GRACE_MS
            if len(recent.rows) < len(forecast.bars) and now_ms < expiry:
                continue
            # Use the issuance date for the whole batch.
            issued = datetime.fromtimestamp(recent.issued_at / 1000, tz=timezone.utc)
            day = evaluation_day(issued, markets.get(symbol))
            key = _accuracy_key(symbol, forecast.model)
            writes.eval(
                _SETTLE, 3, pending_error_key(symbol), f"{key}:{day}", f"{key}:latest",
                raw, recent.model_dump_json(), EVALUATION_TTL_SECONDS,
            )
    await writes.execute()


async def read_accuracy(redis, symbol: str, model: str, day: date) -> tuple[ForecastAccuracy, ForecastSnapshot | None]:
    key = _accuracy_key(symbol, model)
    pipe = redis.pipeline(transaction=True)
    pipe.hmget(f"{key}:latest", ("report", "forecast"))
    pipe.hgetall(f"{key}:{day}")
    (recent, comparison), totals = await pipe.execute()
    daily = []
    for step in range(1, ERROR_HORIZON + 1):
        count = int(totals.get(f"count:{step}", 0))
        if count:
            daily.append(AverageError(
                step=step, count=count, mae=float(totals[f"error:{step}"]) / count,
                baseline_mae=float(totals[f"baseline:{step}"]) / count,
            ))
    result = ForecastAccuracy(
        trading_date=day, recent=RecentErrors.model_validate_json(recent) if recent else None, daily=daily,
    )
    return result, ForecastSnapshot.model_validate_json(comparison) if comparison else None
