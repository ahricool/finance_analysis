"""Evaluate the selected Live preset on public closed bars independently of account reconciliation."""
import asyncio
import json
import logging
import time

from finance_analysis.contracts.service import key, read_json
from finance_analysis.crypto_strategy.catalog import INTERVAL_SECONDS, SYMBOL, config
from finance_analysis.crypto_strategy.service import active
from finance_analysis.database.repositories import contracts, paper_trade
from finance_analysis.paper_trade.strategies import perpetual_drive as drive
from finance_analysis.paper_trade.strategy import STRATEGIES, closed_closes

logger = logging.getLogger(__name__)
OBSERVATION_KEY = "futures:live:v1:strategy-observation"


def selection():
    with paper_trade.session_scope() as session:
        period = active(session, "live")
        return (period.id, period.strategy) if period else None


async def observe(redis, strategy, now):
    settings = config(strategy)
    bars = await read_json(redis, key(SYMBOL, "minute"), [])
    if strategy == drive.TYPE:
        if not 15_000 <= now % drive.PERIOD <= 90_000:
            return None
        benchmark = await read_json(redis, key(drive.BENCHMARK, "minute"), [])
        daily = await asyncio.to_thread(contracts.daily, SYMBOL, 17)
        return drive.evaluate(bars, benchmark, daily, now, settings)
    closed = closed_closes(bars, now, settings["slow"] * 3 + 1)
    if closed:
        stamp, closes = closed
        direction, evidence = STRATEGIES[strategy](closes, settings)
        return stamp, direction, evidence
    return None


async def run(redis):
    while True:
        start = time.monotonic()
        try:
            current = await asyncio.to_thread(selection)
            if current:
                period, strategy = current
                now = int(time.time() * 1000)
                signal = await observe(redis, strategy, now)
                await redis.set(OBSERVATION_KEY, json.dumps({
                    "period": period, "strategy": strategy, "evaluated_at": now,
                    "bar": signal[0] if signal else None, "direction": signal[1] if signal else None,
                }), ex=30)
        except Exception:
            logger.exception("Live strategy observation failed")
        await asyncio.sleep(max(0, INTERVAL_SECONDS - (time.monotonic() - start)))
