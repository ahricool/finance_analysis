"""Single elected streamer publishes shared USD-M contract data to DB and Redis."""
import asyncio
import json
import logging
import time

from redis.exceptions import RedisError

from finance_analysis.database.repositories import contracts as repository
from finance_analysis.integrations.crypto.binance import BinanceClient

logger = logging.getLogger(__name__)
MINUTE = 60_000
DAY = 86_400_000
WINDOW = 1440 * MINUTE
PREFIX = "futures:market:v1"


def minute_start(now):
    return now // MINUTE * MINUTE


def window_start(now):
    return minute_start(now) - WINDOW + MINUTE


def merge_minutes(previous, fresh, now):
    bars = {bar["timestamp"]: bar for bar in (*previous, *fresh)
            if window_start(now) <= bar["timestamp"] <= minute_start(now)}
    return [bars[key] for key in sorted(bars)]


def key(symbol, kind):
    return f"{PREFIX}:{symbol}:{kind}"


async def read_json(redis, name, default):
    raw = await redis.get(name)
    return json.loads(raw) if raw else default


class ContractCollector:
    def __init__(self, redis, client):
        self.redis = redis
        self.client = client
        self.minute_slots = asyncio.Semaphore(4)
        self.daily_slots = asyncio.Semaphore(2)

    async def symbols(self):
        return [row["symbol"] for row in await asyncio.to_thread(repository.contracts)]

    async def quote_tick(self):
        symbols = await self.symbols()
        if not symbols:
            return
        quotes = await self.client.quotes()
        pipe = self.redis.pipeline(transaction=True)
        for symbol in symbols:
            if symbol in quotes:
                pipe.set(key(symbol, "quote"), json.dumps(quotes[symbol]), ex=60)
        await pipe.execute()

    async def minute_tick(self, symbol):
        async with self.minute_slots:
            now = int(time.time() * 1000)
            previous = await read_json(self.redis, key(symbol, "minute"), [])
            # Refresh recent confirmed candles as well as the forming minute.
            start = max(window_start(now), previous[-1]["timestamp"] - 2 * MINUTE) if previous else window_start(now)
            fresh = await self.client.klines(symbol, "1m", start, limit=1500 if minute_start(now) - start >= 99 * MINUTE else 99)
            merged = merge_minutes(previous, fresh, now)
            if fresh:
                await self.redis.set(key(symbol, "minute"), json.dumps(merged), ex=WINDOW // 1000)

    async def daily_tick(self, symbol):
        async with self.daily_slots:
            now = int(time.time() * 1000)
            today = now // DAY * DAY
            latest = await asyncio.to_thread(repository.latest_daily, symbol)
            cursor = latest if latest is not None else today - 1825 * DAY
            while cursor <= today:
                rows = await self.client.klines(symbol, "1d", cursor)
                if not rows:
                    return
                closed = [bar for bar in rows if bar["timestamp"] < today]
                await asyncio.to_thread(repository.save_daily, symbol, closed)
                current = next((bar for bar in rows if bar["timestamp"] == today), None)
                if current is not None:
                    await self.redis.set(key(symbol, "daily-current"), json.dumps(current), ex=180)
                following = rows[-1]["timestamp"] + DAY
                if following <= cursor:
                    raise ValueError("Daily history did not advance")
                cursor = following

    async def collection_tick(self, getter):
        symbols = await self.symbols()

        async def one(symbol):
            try:
                await getter(symbol)
            except Exception:
                logger.warning("USD-M market data unavailable for %s", symbol, exc_info=True)

        await asyncio.gather(*(one(symbol) for symbol in symbols))

    async def loop(self, tick, interval):
        while True:
            try:
                await tick()
            except Exception:
                logger.warning("USD-M contract collection failed", exc_info=True)
            await asyncio.sleep(interval)

    async def run(self):
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(self.loop(self.quote_tick, 5))
            tasks.create_task(self.loop(lambda: self.collection_tick(self.minute_tick), 10))
            tasks.create_task(self.loop(lambda: self.collection_tick(self.daily_tick), 60))


async def run_collector(redis):
    client = BinanceClient()
    try:
        await ContractCollector(redis, client).run()
    finally:
        await client.close()


async def live_snapshot(redis, symbol=None, interval=None):
    contracts = await asyncio.to_thread(repository.contracts)
    keys = [key(row["symbol"], "quote") for row in contracts]
    try:
        quotes = await redis.mget(keys) if keys else []
    except RedisError:
        quotes = [None] * len(keys)
    rows = [{**row, "quote": json.loads(raw) if raw else None} for row, raw in zip(contracts, quotes, strict=True)]
    bars = None
    current_daily = None
    if symbol and symbol in {row["symbol"] for row in rows}:
        try:
            if interval != "1d":
                bars = merge_minutes([], await read_json(redis, key(symbol, "minute"), []), int(time.time() * 1000))
            if interval != "1m":
                current_daily = await read_json(redis, key(symbol, "daily-current"), None)
                if current_daily and current_daily["timestamp"] != int(time.time() * 1000) // DAY * DAY:
                    current_daily = None
        except RedisError:
            # Keep the editable universe and persisted daily chart available.
            bars = [] if interval != "1d" else None
            current_daily = None
    return {"items": rows, "symbol": symbol, "minutes": bars, "daily_current": current_daily}
