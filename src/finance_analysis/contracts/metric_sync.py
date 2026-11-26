"""Background loops owned by the elected Streamer, independent of market WS reconnects."""
import asyncio
import json
import logging
import time

from finance_analysis.contracts.metrics import DAY, ENDPOINTS, HOUR, MINUTE, STEP, aligned, normalize
from finance_analysis.contracts.metrics import price_buckets, summarize_hour
from finance_analysis.contracts.service import key, now_ms, read_json
from finance_analysis.database.repositories import contracts as repo
from finance_analysis.integrations.crypto.binance import MarketCooldown, number

logger = logging.getLogger(__name__)
SOURCES = ("price", *ENDPOINTS)
PAGE = 240  # 1200 one-minute candles or 240 native statistics per page


async def collect(redis, client, symbol, source, start, end, recent):
    if source == "price":
        samples = {}
        if recent:
            bars = await read_json(redis, key(symbol, "minute"), [])
            samples = price_buckets([b for b in bars if b.get("closed") is True], start, end, "binance_ws_rest_1m")
        missing = [t for t in range(start, end + STEP, STEP) if t not in samples]
        if missing:
            first, last = missing[0] - STEP, missing[-1]
            try:
                bars = await client.klines(symbol, "1m", first, limit=(last - first) // MINUTE, end=last - 1)
            except Exception:
                # Preserve independently confirmed cache buckets through a REST outage.
                await asyncio.to_thread(repo.save_samples, symbol, source, samples)
                raise
            samples.update(price_buckets(bars, missing[0], last, "binance_rest_1m"))
    else:
        # USD-M filters taker volumes by closing boundary but labels rows by opening time.
        raw = await client.market_get("/futures/data/" + ENDPOINTS[source], {
            "symbol": symbol, "period": "5m", "startTime": start,
            "endTime": min(now_ms(), end + STEP - 1), "limit": (end - start) // STEP + 2,
        }, private_stats=source.startswith("top_"))
        samples = normalize(source, raw, symbol, start, end)
    await asyncio.to_thread(repo.save_samples, symbol, source, samples)
    return samples.keys()


async def latest(redis, client, symbols, end):
    slots = asyncio.Semaphore(3)

    async def one(symbol):
        async with slots:
            stored = await asyncio.to_thread(repo.metric_history, symbol, end - HOUR, end, 13)
            indexed = {row["timestamp"]: row for row in stored}
            statuses = {}
            for source in SOURCES:
                missing = [t for t in range(end - HOUR, end + STEP, STEP) if not indexed.get(t, {}).get(source)]
                if not missing:
                    statuses[source] = "ok"
                    continue
                try:
                    found = await collect(redis, client, symbol, source, missing[0], missing[-1], True)
                    if end in missing and end not in found:
                        statuses[source] = "missing"
                    else:
                        statuses[source] = "partial" if set(missing).difference(found) else "ok"
                except PermissionError:
                    statuses[source] = "unauthorized"
                except Exception as exc:
                    statuses[source] = error_status(exc)
            rows = await asyncio.to_thread(repo.metric_history, symbol, end - HOUR, end, 13)
            result = summarize_hour(rows, end)
            result["status"] = statuses
            await redis.set(key(symbol, "metrics"), json.dumps(result), ex=600)

            return symbol if any(s in {"missing", "partial", "rate_limited", "unavailable"} for s in statuses.values()) else None

    async with asyncio.TaskGroup() as tasks:
        runs = [tasks.create_task(one(s)) for s in symbols]
    return {run.result() for run in runs if run.result()}


def error_status(exc):
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(exc, MarketCooldown) or status in (418, 429):
        return "rate_limited"
    if status in (401, 403):
        return "unauthorized"
    logger.warning("Contract statistics unavailable (%s)", type(exc).__name__)
    return "unavailable"


async def backfill_page(redis, client, symbol, source, end):
    """Checkpoint each successful source separately, including legitimate empty pages."""
    cursor_key = key(symbol, "backfill:" + source)
    raw = await redis.get(cursor_key)
    cursor = int(raw) if raw else end - HOUR
    if cursor == 0:
        return
    floor = end - 30 * DAY + STEP
    if cursor < floor:
        await redis.set(cursor_key, 0, ex=86400)
        return
    start = max(floor, cursor - (PAGE - 1) * STEP)
    saved = await asyncio.to_thread(repo.sample_times, symbol, source, start, cursor)
    missing = [t for t in range(start, cursor + STEP, STEP) if t not in saved]
    if missing:
        await collect(redis, client, symbol, source, missing[0], missing[-1], False)
    # Revisit remaining holes as late samples become available.
    await redis.set(cursor_key, 0 if start <= floor else start - STEP, ex=86400 if start <= floor else 31 * 86400)


async def latest_loop(redis, client, ready):
    # Keep successful symbols asleep until the next boundary. Retry late sources
    # within the current window and pick up additions without restarting a worker.
    due = {}
    while True:
        try:
            now = now_ms()
            end = aligned(now)
            symbols = {row["symbol"] for row in await asyncio.to_thread(repo.contracts)}
            due = {s: t for s, t in due.items() if s in symbols}
            targets = sorted(s for s in symbols if due.get(s, 0) <= now)
            if targets:
                pending = await latest(redis, client, targets, end)
                for symbol in targets:
                    due[symbol] = min(end + STEP, now_ms() + MINUTE) if symbol in pending else end + STEP
            ready.set()
        except Exception:
            logger.exception("Contract statistics cycle failed")
        await asyncio.sleep(5)


async def backfill_loop(redis, client, ready):
    await ready.wait()
    retry_after = {}
    while True:
        try:
            symbols = await asyncio.to_thread(repo.contracts)
            for row in symbols:
                for source in SOURCES:
                    job = (row["symbol"], source)
                    if time.monotonic() < retry_after.get(job, 0):
                        continue
                    try:
                        await backfill_page(redis, client, *job, aligned(now_ms()))
                        retry_after.pop(job, None)
                    except Exception as exc:
                        if not isinstance(exc, PermissionError):
                            error_status(exc)
                        retry_after[job] = time.monotonic() + 300
        except Exception:
            logger.exception("Contract statistics backfill failed")
        await asyncio.sleep(15)


async def metric_loop(redis, client):
    ready = asyncio.Event()
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(latest_loop(redis, client, ready))
        tasks.create_task(backfill_loop(redis, client, ready))


def book_snapshot(item):
    bid, ask = number(item["bidPrice"]), number(item["askPrice"])
    if not 0 < bid <= ask:
        raise ValueError("Invalid BBO")
    return {"bid": bid, "ask": ask, "spread_bps": 20000 * (ask - bid) / (ask + bid),
            "timestamp": int(item["time"])}


def depth_snapshot(item):
    result = {"timestamp": int(item["T"])}
    for side in ("bids", "asks"):
        levels = [(number(p), number(q)) for p, q in item[side][:10]]
        if any(p <= 0 or q < 0 for p, q in levels):
            raise ValueError("Invalid depth level")
        result[side] = sum(p * q for p, q in levels) if levels else None
        result[side + "_levels"] = len(levels)
    return result


async def cache_fresh(redis, symbol, kind, item, ttl):
    remaining = min(ttl, ttl - (now_ms() - item["timestamp"]) / 1000)
    if remaining <= 0 or item["timestamp"] > now_ms() + 1000:
        return
    previous = await read_json(redis, key(symbol, kind), {})
    if previous.get("timestamp", 0) < item["timestamp"]:
        await redis.set(key(symbol, kind), json.dumps(item), px=max(1, int(remaining * 1000)))


async def liquidity_loop(redis, client):
    while True:
        tick = time.monotonic()
        try:
            symbols = {r["symbol"] for r in await asyncio.to_thread(repo.contracts)}
            if symbols:
                try:
                    books = await client.market_get("/fapi/v1/ticker/bookTicker")
                except Exception as exc:
                    error_status(exc)
                    books = []
                for item in books:
                    if item["symbol"] in symbols:
                        try:
                            await cache_fresh(redis, item["symbol"], "book", book_snapshot(item), 60)
                        except (KeyError, ValueError):
                            continue
                for symbol in sorted(symbols):
                    if await redis.get(key(symbol, "depth-demand")):
                        try:
                            item = await client.market_get("/fapi/v1/depth", {"symbol": symbol, "limit": 10})
                            await cache_fresh(redis, symbol, "depth", depth_snapshot(item), 15)
                        except Exception as exc:
                            error_status(exc)
        except Exception as exc:
            error_status(exc)
        await asyncio.sleep(max(1, 5 - (time.monotonic() - tick)))
