"""Latest live forecasts are disposable and separate from market data."""

from pydantic import ValidationError

from finance_analysis.minute_forecast.models import HORIZON, MINUTE_MS, ForecastSnapshot

TTL_SECONDS = 15 * 60

# The first result for a minute is frozen across a Streamer restart/retry. An
# older inference must never replace the snapshot for a later confirmed minute.
_PUBLISH = """
local clock = redis.call('TIME')
if tonumber(clock[1]) * 1000 + tonumber(clock[2]) / 1000 >= tonumber(ARGV[4]) then return 0 end
local old = redis.call('GET', KEYS[1])
if old then
    local ok, payload = pcall(cjson.decode, old)
    if ok and type(payload) == 'table' and tonumber(payload.anchor)
        and tonumber(payload.anchor) >= tonumber(ARGV[1]) then return 0 end
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
redis.call('ZADD', KEYS[2], ARGV[1], ARGV[2])
redis.call('ZREMRANGEBYRANK', KEYS[2], 0, -17)
redis.call('EXPIRE', KEYS[2], ARGV[3])
return 1
"""


def forecast_key(symbol: str) -> str:
    return f"rt:forecast:1m:v1:{symbol}"


def _decode(raw) -> ForecastSnapshot | None:
    if raw is None:
        return None
    try:
        return ForecastSnapshot.model_validate_json(raw)
    except ValidationError:
        return None


async def latest_forecast(redis, symbol: str) -> ForecastSnapshot | None:
    return _decode(await redis.get(forecast_key(symbol)))


async def comparison_forecast(redis, symbol: str, now_ms: int) -> ForecastSnapshot | None:
    # A full horizon is settled after all five target candles could have closed.
    cutoff = now_ms - now_ms % MINUTE_MS - (HORIZON + 1) * MINUTE_MS
    found = await redis.zrevrangebyscore(f"{forecast_key(symbol)}:recent", cutoff, "-inf", start=0, num=1)
    return _decode(found[0]) if found else None


async def publish_forecast(redis, forecast: ForecastSnapshot) -> None:
    key = forecast_key(forecast.symbol)
    await redis.eval(_PUBLISH, 2, key, f"{key}:recent", forecast.anchor, forecast.model_dump_json(),
                     TTL_SECONDS, forecast.bars[0].timestamp + MINUTE_MS)
