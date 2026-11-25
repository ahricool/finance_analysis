"""Daily USD-M history maintenance, independent of the realtime Streamer."""
import asyncio
import logging
from datetime import datetime, timezone

from finance_analysis.database.repositories import contracts as repository
from finance_analysis.integrations.crypto.binance import BinanceClient

logger = logging.getLogger(__name__)
DAY = 86_400_000
HISTORY_DAYS = 1825
SETTLE_MS = 30 * 60_000


class DailySyncError(RuntimeError):
    """At least one contract's closed history could not be reconciled."""


def target_day(now):
    """Most recent UTC day closed for at least 30 minutes."""
    return (now - SETTLE_MS) // DAY * DAY - DAY


async def fetch_history(client, symbol, start, end):
    records = {}
    cursor = start
    while cursor <= end:
        rows = await client.klines(symbol, "1d", cursor, limit=1000, end=end + DAY - 1)
        if not rows:
            break
        records.update((bar["timestamp"], bar) for bar in rows if cursor <= bar["timestamp"] <= end)
        following = rows[-1]["timestamp"] + DAY
        if following <= cursor:
            raise DailySyncError("Daily pagination did not advance")
        cursor = following
    expected = set(range(start, end + DAY, DAY))
    if records.keys() != expected:
        raise DailySyncError(f"Missing {len(expected - records.keys())} exchange daily candles")
    return [records[stamp] for stamp in sorted(records)]


async def sync_symbol(client, symbol, listed_at, target):
    start = max(target - (HISTORY_DAYS - 1) * DAY, listed_at // DAY * DAY)
    if start > target:
        return {"symbol": symbol, "mode": "not_listed_on_target", "bars": 0}
    actual = await asyncio.to_thread(repository.daily_timestamps, symbol, start, target)
    expected_history = set(range(start, target, DAY))
    if expected_history.issubset(actual) and target in actual:
        return {"symbol": symbol, "mode": "up_to_date", "bars": 0}
    mode = "incremental" if expected_history.issubset(actual) else "full"
    rows = await fetch_history(client, symbol, target if mode == "incremental" else start, target)
    # Only write once the entire requested range is verified. Existing rows
    # remain intact on failed or partial upstream responses.
    await asyncio.to_thread(repository.save_daily, symbol, rows)
    return {"symbol": symbol, "mode": mode, "bars": len(rows)}


async def sync_daily(client, now):
    target = target_day(now)
    symbols = await asyncio.to_thread(repository.contracts)
    if not symbols:
        return {"target": datetime.fromtimestamp(target / 1000, timezone.utc).date().isoformat(), "results": []}
    source = await client.exchange_info()
    listing = {
        row["symbol"]: int(row["onboardDate"])
        for row in source["symbols"]
        if row.get("contractType") in {"PERPETUAL", "TRADIFI_PERPETUAL"}
        and row.get("marginAsset") == row.get("quoteAsset") == "USDT"
        and row.get("onboardDate")
    }
    slots = asyncio.Semaphore(2)

    async def one(row):
        symbol = row["symbol"]
        async with slots:
            try:
                if symbol not in listing:
                    raise DailySyncError("Exchange listing date unavailable")
                return await sync_symbol(client, symbol, listing[symbol], target)
            except Exception:
                logger.warning("USD-M daily synchronization failed for %s", symbol, exc_info=True)
                return {"symbol": symbol, "mode": "failed", "bars": 0}

    results = await asyncio.gather(*(one(row) for row in symbols))
    failed = [row["symbol"] for row in results if row["mode"] == "failed"]
    if failed:
        raise DailySyncError("Daily history incomplete: " + ", ".join(failed))
    return {"target": datetime.fromtimestamp(target / 1000, timezone.utc).date().isoformat(), "results": results}


async def run_daily_sync():
    client = BinanceClient()
    try:
        # Source server time controls the UTC boundary rather than local TZ.
        now = int((await client.server_time()).timestamp() * 1000)
        return await sync_daily(client, now)
    finally:
        await client.close()
