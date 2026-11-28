"""Latest live forecasts are disposable and separate from market data."""

from pydantic import ValidationError

from finance_analysis.minute_forecast.models import ERROR_HORIZON, MINUTE_MS, ForecastSnapshot

TTL_SECONDS = 15 * 60
EVALUATION_TTL_SECONDS = 3 * 24 * 60 * 60

# The first result for a minute is frozen across a Streamer restart/retry. An
# older inference must never replace the snapshot for a later confirmed minute.
_PUBLISH = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + tonumber(clock[2]) / 1000
if now >= tonumber(ARGV[4]) then return 0 end
local old = redis.call('GET', KEYS[1])
if old then
    local ok, payload = pcall(cjson.decode, old)
    if ok and type(payload) == 'table' and tonumber(payload.anchor)
        and tonumber(payload.anchor) >= tonumber(ARGV[1]) then return 0 end
end
local ttl = math.max(tonumber(ARGV[3]), math.ceil((tonumber(ARGV[7]) - now) / 1000))
redis.call('SET', KEYS[1], ARGV[2], 'EX', ttl)
if ARGV[9] == '0' then return 1 end
redis.call('ZADD', KEYS[2], ARGV[1], ARGV[8])
redis.call('ZREMRANGEBYRANK', KEYS[2], 0, -17)
redis.call('EXPIRE', KEYS[2], ARGV[3])
redis.call('ZADD', KEYS[3], ARGV[5], ARGV[8])
redis.call('EXPIRE', KEYS[3], ARGV[6])
return 1
"""


def forecast_key(symbol: str) -> str:
    return f"rt:forecast:1m:v1:{symbol}"


def live_forecast_key(symbol: str) -> str:
    # Invalidate pre-upgrade full-session paths, but keep accuracy and replay keys.
    return f"{forecast_key(symbol)}:live60"


def close_replay_key(symbol: str) -> str:
    return f"{forecast_key(symbol)}:close"


def _decode(raw) -> ForecastSnapshot | None:
    if raw is None:
        return None
    try:
        return ForecastSnapshot.model_validate_json(raw)
    except ValidationError:
        return None


async def latest_forecast(redis, symbol: str) -> ForecastSnapshot | None:
    return _decode(await redis.get(live_forecast_key(symbol)))


async def close_replay_forecast(redis, symbol: str) -> ForecastSnapshot | None:
    replay = _decode(await redis.get(close_replay_key(symbol)))
    return replay if replay is not None and replay.close_replay else None


async def comparison_forecast(redis, symbol: str, now_ms: int) -> ForecastSnapshot | None:
    # Compatibility fallback for pre-upgrade snapshots and older chart clients.
    cutoff = now_ms - now_ms % MINUTE_MS - (ERROR_HORIZON + 1) * MINUTE_MS
    found = await redis.zrevrangebyscore(f"{forecast_key(symbol)}:recent", cutoff, "-inf", start=0, num=1)
    return _decode(found[0]) if found else None


async def publish_forecast(redis, forecast: ForecastSnapshot, *, track_accuracy: bool = True) -> None:
    key = forecast_key(forecast.symbol)
    # Keep the established short-horizon accuracy series without queuing every rolling path until the close.
    comparison = forecast.model_copy(update={"bars": forecast.bars[:ERROR_HORIZON], "session_close": None})
    await redis.eval(
        _PUBLISH, 3, live_forecast_key(forecast.symbol), f"{key}:recent", pending_error_key(forecast.symbol),
        forecast.anchor, forecast.model_dump_json(), TTL_SECONDS, forecast.bars[0].timestamp + MINUTE_MS,
        comparison.bars[-1].timestamp + MINUTE_MS, EVALUATION_TTL_SECONDS,
        forecast.session_close or 0, comparison.model_dump_json(), int(track_accuracy),
    )


def pending_error_key(symbol: str) -> str:
    return f"{forecast_key(symbol)}:pending-errors"
