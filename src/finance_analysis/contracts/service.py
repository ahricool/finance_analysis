"""Single elected streamer publishes real-time USD-M contract data to Redis."""
import asyncio
from datetime import UTC, datetime
import json
import logging
import time

import websockets
from redis.exceptions import RedisError

from finance_analysis.intraday_options.opportunity_alert import alert_opportunity
from finance_analysis.contracts.analysis import summarize
from finance_analysis.contracts.metrics import LIST_METRIC_MAX_AGE, aligned, summary_readings
from finance_analysis.database.repositories import contracts as repository
from finance_analysis.integrations.crypto.binance import BinanceClient, number, parse_bar

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
    if not raw:
        return default
    value = json.loads(raw)
    if name.endswith(":minute"):
        # Consumers must not mistake a missing WS close frame for a finalized
        # historical candle. Keep only the current forming minute.
        minute = minute_start(now_ms())
        return [bar for bar in value if bar.get("closed") is not False or bar["timestamp"] == minute]
    return value


WS_MARKET = "wss://fstream.binance.com/market/stream"
QUOTE_TTL = 60
MINUTE_TTL = WINDOW // 1000


def now_ms():
    return int(time.time() * 1000)


def missing_minutes(bars, now):
    """Check the actual natural-minute grid, not just the number of records."""
    indexed = {b["timestamp"]: b for b in bars}
    current = minute_start(now)
    return [
        stamp for stamp in range(window_start(now), current + MINUTE, MINUTE)
        if stamp not in indexed or (stamp != current and not indexed[stamp].get("closed", True))
    ]


def complete_minutes(bars, now):
    return not missing_minutes(bars, now)


def stream_url(symbols):
    streams = [
        f"{symbol.lower()}@{kind}" for symbol in sorted(symbols)
        for kind in ("ticker", "markPrice@1s", "kline_1m", "kline_1d")
    ]
    return WS_MARKET + "?streams=" + "/".join(streams)


def ws_bar(event):
    k = event["k"]
    interval = k["i"]
    period = {"1m": MINUTE, "1d": DAY}[interval]
    stamp = int(k["t"])
    if stamp % period or int(k["T"]) != stamp + period - 1 or not isinstance(k["x"], bool):
        raise ValueError("Invalid Binance stream candle boundary")
    row = parse_bar([stamp, k["o"], k["h"], k["l"], k["c"], k["v"], k["T"], k["q"]])
    return {**row, "closed": k["x"], "event_time": int(event["E"])}


class UniverseChanged(Exception):
    """Reconnect to the new shared contract subscriptions."""


class ContractCollector:
    def __init__(self, redis, client, connect=None):
        self.redis = redis
        self.client = client
        self.connect = connect or websockets.connect
        self.minute_slots = asyncio.Semaphore(4)
        self.minutes = {}
        self.quotes = {}
        self.funding = {}
        self.daily_current = {}
        self.dirty = set()
        self.alert_tasks = set()

    async def symbols(self):
        return {row["symbol"] for row in await asyncio.to_thread(repository.contracts)}

    async def load(self, symbols):
        self.minutes = {}
        self.quotes, self.funding, self.daily_current = {}, {}, {}
        self.dirty.clear()
        now = now_ms()
        for symbol in symbols:
            mark = await read_json(self.redis, key(symbol, "mark"), None)
            if mark:
                self.funding[symbol] = mark
            rows = await read_json(self.redis, key(symbol, "minute"), [])
            cached = merge_minutes([], rows, now)
            # Legacy snapshots have no close flag. Their final historical bar
            # may have been forming at disconnect, so force REST reconciliation.
            self.minutes[symbol] = {
                b["timestamp"]: {
                    **b,
                    "closed": b.get("closed", b["timestamp"] < minute_start(now) and b is not cached[-1]),
                }
                for b in cached
            }
            if cached:
                self.dirty.add((symbol, "analysis"))
            if cached and any("closed" not in b for b in cached):
                self.dirty.add((symbol, "minute"))

    def update_minute(self, symbol, row, now):
        stamp = row["timestamp"]
        if not window_start(now) <= stamp <= minute_start(now):
            return
        rows = self.minutes[symbol]
        previous = rows.get(stamp)
        if previous:
            if previous.get("closed") is True and not row.get("closed"):
                return
            if (previous.get("closed") == row.get("closed")
                    and previous.get("event_time", 0) > row.get("event_time", 0)):
                return
        if previous and all(previous.get(k) == value for k, value in row.items()):
            return
        if row.get("closed"):
            self.dirty.add((symbol, "analysis"))
        rows[stamp] = {**row, "received_at_ms": now}
        self.dirty.add((symbol, "minute"))

    async def repair_minutes(self, symbol):
        async with self.minute_slots:
            now = now_ms()
            missing = missing_minutes(self.minutes[symbol].values(), now)
            if not missing:
                return
            # Start at the earliest gap; do not refetch a full day for a short
            # disconnect. Incoming WS events continue meanwhile.
            start = missing[0]
            count = (minute_start(now) - start) // MINUTE + 1
            fresh = await self.client.klines(symbol, "1m", start, limit=1500 if count == 1440 else count)
            for bar in fresh:
                stamp = bar["timestamp"]
                # A REST snapshot begun before live updates must not overwrite
                # a newer WS forming candle or a confirmed close.
                if stamp >= minute_start(now) and stamp in self.minutes[symbol]:
                    continue
                self.update_minute(symbol, {**bar, "closed": stamp < minute_start(now)}, now_ms())

    def accept_event(self, event, symbols, now):
        symbol, kind = event["s"], event["e"]
        if symbol not in symbols:
            return
        event_time = int(event["E"])
        if event_time > now + MINUTE:
            raise ValueError("Future Binance event")
        if kind == "24hrTicker":
            previous = self.quotes.get(symbol)
            if previous and previous["timestamp"] >= event_time:
                return
            quote = {
                "price": number(event["c"]), "change_pct": number(event["P"]),
                "turnover": number(event["q"]), "timestamp": event_time,
            }
            if quote["price"] <= 0 or quote["turnover"] < 0:
                raise ValueError("Invalid Binance ticker")
            self.quotes[symbol] = quote
            self.dirty.add((symbol, "quote"))
        elif kind == "markPriceUpdate":
            previous = self.funding.get(symbol)
            if not previous or previous["timestamp"] < event_time:
                mark = number(event["p"]) if event.get("p") else None
                index = number(event["i"]) if event.get("i") else None
                self.funding[symbol] = {
                    "timestamp": event_time, "mark_price": mark, "index_price": index,
                    "basis": mark / index - 1 if mark and index else None,
                    "funding_rate": number(event["r"]), "next_funding": int(event["T"]) if event.get("T") else None,
                }
                self.dirty.add((symbol, "mark"))
                if symbol in self.quotes:
                    self.dirty.add((symbol, "quote"))
        elif kind == "kline":
            row = ws_bar(event)
            if event["k"]["i"] == "1m":
                self.update_minute(symbol, row, now)
            elif row["timestamp"] == now // DAY * DAY:
                previous = self.daily_current.get(symbol)
                if not previous or row["event_time"] > previous["event_time"]:
                    self.daily_current[symbol] = row
                    self.dirty.add((symbol, "daily-current"))

    async def flush(self):
        """Coalesce updates: never serialize a 1440-bar array for each WS frame."""
        dirty, self.dirty = self.dirty, set()
        if not dirty:
            return
        now = now_ms()
        pipe = self.redis.pipeline(transaction=True)
        writes = 0
        analyses = {}
        for symbol, kind in dirty:
            if kind == "analysis":
                analyses[symbol] = sorted(self.minutes[symbol].values(), key=lambda b: b["timestamp"])
            elif kind == "minute":
                rows = self.minutes[symbol]
                merged = merge_minutes([], rows.values(), now)
                self.minutes[symbol] = {row["timestamp"]: row for row in merged}
                if merged:
                    pipe.set(key(symbol, kind), json.dumps(merged), ex=MINUTE_TTL)
                    writes += 1
            elif kind == "mark":
                mark = self.funding[symbol]
                ttl = QUOTE_TTL - max(0, (now - mark["timestamp"]) // 1000)
                if ttl > 0:
                    pipe.set(key(symbol, kind), json.dumps(mark), ex=ttl)
                    writes += 1
            elif kind == "quote":
                quote = self.quotes[symbol]
                age = max(0, (now - quote["timestamp"]) // 1000)
                if age >= QUOTE_TTL:
                    continue
                funding = self.funding.get(symbol)
                rate = funding["funding_rate"] if funding and now - funding["timestamp"] < QUOTE_TTL * 1000 else None
                pipe.set(key(symbol, kind), json.dumps({**quote, "funding_rate": rate,
                                                       "funding_timestamp": funding["timestamp"] if funding else None}), ex=QUOTE_TTL - age)
                writes += 1
            elif kind == "daily-current":
                row = self.daily_current[symbol]
                if row["timestamp"] == now // DAY * DAY:
                    pipe.set(key(symbol, kind), json.dumps(row), ex=180)
                    writes += 1
        # Freeze all mutable market inputs before yielding to live WS updates.
        alerts = []
        for symbol, bars in analyses.items():
            summary = await asyncio.to_thread(summarize, symbol, bars, now, include_alerts=True)
            candidates = summary.pop("alerts") if summary else []
            pipe.set(key(symbol, "analysis"), json.dumps(summary), ex=120)
            writes += 1
            quote = self.quotes.get(symbol)
            if quote:
                alerts.extend((symbol, b, summary["as_of"], quote["timestamp"]) for b in candidates)
        if writes:
            await pipe.execute()
        for symbol, candidate, as_of, quote_at in alerts:
            task = asyncio.create_task(alert_opportunity(
                self.redis, symbol, candidate, datetime.fromtimestamp(as_of / 1000, UTC),
                datetime.fromtimestamp(quote_at / 1000, UTC), datetime.now(UTC),
            ))
            self.alert_tasks.add(task)
            task.add_done_callback(self.alert_tasks.discard)

    async def receive(self, socket, symbols):
        while True:
            raw = await asyncio.wait_for(socket.recv(), timeout=60)
            try:
                event = json.loads(raw)["data"]
                self.accept_event(event, symbols, now_ms())
            except (ValueError, TypeError, KeyError, ArithmeticError):
                logger.debug("Invalid USD-M market stream frame")

    async def repair_all(self, symbols):
        async def one(symbol):
            try:
                await self.repair_minutes(symbol)
            except Exception:
                logger.warning("USD-M minute backfill failed for %s", symbol, exc_info=True)

        await asyncio.gather(*(one(symbol) for symbol in symbols))

    async def maintain(self, symbols, warmup=None):
        if warmup is not None:
            await warmup
        last_repair = -60.0
        while True:
            if await self.symbols() != symbols:
                raise UniverseChanged
            if time.monotonic() - last_repair >= 60:
                await self.repair_all(symbols)
                last_repair = time.monotonic()
            await asyncio.sleep(10)

    async def flush_loop(self):
        while True:
            await asyncio.sleep(1)
            await self.flush()

    async def run_session(self, symbols):
        await self.load(symbols)
        # Start history and the live subscription independently: REST failure
        # must not prevent quotes or live candles from arriving over WS.
        warmup = asyncio.create_task(self.repair_all(symbols))
        tasks = []
        try:
            async with self.connect(stream_url(symbols), open_timeout=15, ping_interval=30, ping_timeout=20) as socket:
                tasks = [
                    asyncio.create_task(self.receive(socket, symbols)),
                    asyncio.create_task(self.maintain(symbols, warmup)),
                    asyncio.create_task(self.flush_loop()),
                ]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
        except asyncio.CancelledError:
            warmup.cancel()
            raise
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                warmup.cancel()
            # If the handshake failed, allow initial REST warmup to finish.
            # Otherwise stop the old session before another can write.
            await asyncio.gather(*tasks, warmup, return_exceptions=True)
            await asyncio.gather(*tuple(self.alert_tasks), return_exceptions=True)
            await self.flush()

    async def run(self):
        delay = 1
        while True:
            started = time.monotonic()
            try:
                symbols = await self.symbols()
                if not symbols:
                    await asyncio.sleep(10)
                    continue
                await self.run_session(symbols)
                delay = 1
            except UniverseChanged:
                delay = 1
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("USD-M market stream disconnected; reconnecting", exc_info=True)
                if time.monotonic() - started >= 60:
                    delay = 1
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)


async def run_collector(redis):
    client = BinanceClient()
    try:
        from finance_analysis.contracts.metric_sync import liquidity_loop, metric_loop

        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(ContractCollector(redis, client).run())
            tasks.create_task(metric_loop(redis, client))
            tasks.create_task(liquidity_loop(redis, client))
    finally:
        await client.close()


async def cached_candles(redis, symbol, interval):
    """Read just the requested symbol's UTC candle window from the stream cache."""
    bars = None
    current_daily = None
    try:
        if interval != "1d":
            bars = merge_minutes([], await read_json(redis, key(symbol, "minute"), []), now_ms())
        if interval != "1m":
            current_daily = await read_json(redis, key(symbol, "daily-current"), None)
            if current_daily and current_daily["timestamp"] != now_ms() // DAY * DAY:
                current_daily = None
    except RedisError:
        # Keep the editable universe and persisted daily chart available.
        bars = [] if interval != "1d" else None
        current_daily = None
    return bars, current_daily


async def live_snapshot(redis, symbol=None, interval=None):
    contracts = await asyncio.to_thread(repository.contracts)
    kinds = ("quote", "analysis", "metrics", "mark", "book")
    keys = [key(row["symbol"], kind) for row in contracts for kind in kinds]
    try:
        cached = iter(await redis.mget(keys) if keys else [])
    except RedisError:
        cached = iter(())
    now = now_ms()
    rows = []
    for contract in contracts:
        row = dict(contract)
        for kind in kinds:
            raw = next(cached, None)
            value = json.loads(raw) if raw else None
            if value and kind in ("quote", "mark", "book") and abs(now - value["timestamp"]) >= QUOTE_TTL * 1000:
                value = None
            if value and kind == "metrics":
                readings = value.pop("list_metrics", None)
                if readings is None:
                    readings = summary_readings(value)
                if readings:
                    row["list_metrics"] = {field: reading for field, reading in readings.items()
                                           if 0 <= now - reading["timestamp"] <= LIST_METRIC_MAX_AGE}
                if value["timestamp"] != aligned(now):
                    value = None
            row[kind] = value
        quote = row["quote"]
        if quote and row["mark"]:
            quote["funding_rate"] = row["mark"]["funding_rate"]
            quote["funding_timestamp"] = row["mark"]["timestamp"]
        elif quote and "funding_timestamp" in quote:
            quote["funding_rate"] = quote["funding_timestamp"] = None
        rows.append(row)
    bars = None
    current_daily = None
    if symbol and symbol in {row["symbol"] for row in rows}:
        bars, current_daily = await cached_candles(redis, symbol, interval)
    return {"items": rows, "symbol": symbol, "minutes": bars, "daily_current": current_daily}
