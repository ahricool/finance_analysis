"""Single facade for BTC queries, ingestion, backfill and deterministic evaluation."""

import asyncio
from dataclasses import asdict
from datetime import timedelta

from finance_analysis.core.time import utc_now
from finance_analysis.crypto.config import get_crypto_config
from finance_analysis.crypto.strategy import evaluate


async def run_db(function, *args, **kwargs):
    """Let a bounded DB transaction finish before releasing the streamer leader lock."""
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


class CryptoService:
    def __init__(self, repository=None, realtime=None, binance=None, config=None):
        self.config = config or get_crypto_config()
        if repository is None:
            from finance_analysis.database.repositories.crypto import CryptoRepository

            repository = CryptoRepository()
        self.repository = repository
        self.realtime = realtime
        self.binance = binance
        self.live = dict(
            stream_mode="http_fallback",
            websocket_connected=False,
            last_websocket_message_time=None,
            last_update_time=None,
            last_error=None,
            latest_candle=None,
            recent_closed=[],
            strategy_latest_state=None,
            ready=False,
        )

    async def get_market_state(self):
        cached = await self.realtime.read() if self.realtime else {}
        state = {**self.live, **cached, "enabled": self.config.enabled, "symbol": "BTCUSDT"}
        if not cached and state["latest_candle"] is None:
            # An empty/unavailable Redis must not hide closed facts already in PostgreSQL.
            rows = await run_db(self.get_recent_klines, 5)
            signals = await run_db(self.get_signals, 1)
            state.update(
                recent_closed=rows,
                latest_candle=rows[-1] if rows else None,
                last_update_time=rows[-1]["close_time"] if rows else None,
                strategy_latest_state=signals[0] if signals else None,
            )
        return state

    def get_recent_klines(self, limit=1000):
        return [asdict(row) for row in self.repository.klines(limit=limit)]

    def get_signals(self, limit=50):
        return self.repository.signals(limit)

    def get_strategy_state(self):
        return asdict(self.repository.state())

    async def get_overview(self):
        signals = await run_db(self.get_signals, 1)
        return {
            "symbol": "BTCUSDT",
            "strategy": signals[0] if signals else None,
            "state": await run_db(self.get_strategy_state),
            "market": await self.get_market_state(),
        }

    async def publish(self, **updates):
        self.live.update(updates)
        if self.realtime:
            await self.realtime.write(self.live)

    async def ingest(self, rows, *, calculate=True):
        now = utc_now()
        await run_db(self.repository.upsert_klines, rows, now)
        closed = {row["open_time"]: row for row in self.live["recent_closed"]}
        closed.update({row.open_time: asdict(row) for row in rows if row.closed and row.close_time <= now})
        self.live["recent_closed"] = [closed[key] for key in sorted(closed)[-5:]]
        for row in sorted(rows, key=lambda item: item.open_time):
            current = self.live["latest_candle"]
            if current and (
                row.open_time < current["open_time"]
                or (row.open_time == current["open_time"] and current["closed"] and not row.closed)
            ):
                continue
            self.live["latest_candle"] = asdict(row)
        if calculate and any(row.closed for row in rows):
            await self.evaluate_pending()
        await self.publish(last_update_time=now)

    async def evaluate_pending(self):
        latest_open = await run_db(self.repository.latest_open_time)
        if latest_open is None:
            return
        end = latest_open + timedelta(minutes=1)
        boundary = end.replace(minute=(end.minute // 15) * 15, second=0, microsecond=0)
        snapshots = await run_db(self.repository.signals, 1)
        # Cold start records the first live evaluation, not fictitious historical trades.
        at = snapshots[0]["evaluated_at"] + timedelta(minutes=15) if snapshots else boundary
        while at <= boundary:
            rows = await run_db(self.repository.klines, limit=7 * 1440, as_of=at, start=at - timedelta(days=7))
            snapshot = await run_db(self.repository.evaluate_once, at, lambda state: evaluate(rows, at, state))
            if snapshot:
                self.live["strategy_latest_state"] = snapshot
            at += timedelta(minutes=15)
        if self.live["strategy_latest_state"] is None and snapshots:
            self.live["strategy_latest_state"] = snapshots[0]

    async def backfill(self):
        """Page oldest-first; interrupted backfills restart from the last committed minute."""
        now = await self.binance.server_time()
        end = now.replace(second=0, microsecond=0)
        latest = await run_db(self.repository.latest_open_time)
        start = latest if latest else end - timedelta(days=self.config.initial_history_days)
        while start < end:
            rows = await self.binance.klines(start=start, end=end, limit=1000, as_of=now)
            rows = [row for row in rows if start <= row.open_time < end and row.closed]
            if not rows:
                raise ValueError("Binance history page is empty before the requested end")
            await self.ingest(rows, calculate=False)
            following = rows[-1].close_time
            if following <= start:
                raise ValueError("Binance history page did not advance")
            start = following
        await self.evaluate_pending()
        await self.publish(ready=True)

    async def reconcile(self):
        now = await self.binance.server_time()
        latest = await run_db(self.repository.latest_open_time)
        # A long simultaneous WS/REST outage uses the same paginated startup catch-up.
        if not self.live["ready"] or (latest is not None and now - latest > timedelta(minutes=5)):
            await self.backfill()
        await self.ingest(await self.binance.klines(limit=5, as_of=now))
