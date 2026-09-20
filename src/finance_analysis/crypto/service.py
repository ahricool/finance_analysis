"""BTC strategy reads and scheduled evaluation; market data is never persisted."""

import asyncio
from dataclasses import asdict
from datetime import timedelta

from finance_analysis.crypto.config import get_crypto_config
from finance_analysis.crypto.features import contiguous_tail
from finance_analysis.crypto.strategy import evaluate
from finance_analysis.integrations.crypto.binance import BinanceClient


class CryptoService:
    def __init__(self, repository=None, binance=None, config=None):
        self.config = config or get_crypto_config()
        if repository is None:
            from finance_analysis.database.repositories.crypto import CryptoRepository

            repository = CryptoRepository()
        self.repository = repository
        self.binance = binance

    def get_signals(self, limit=50, **filters):
        return self.repository.signals(limit, **filters)

    def get_performance(self):
        from finance_analysis.crypto.performance import performance

        return performance(self.repository.signals(None), self.repository.state())

    def get_overview(self):
        signals = self.get_signals(1)
        return {
            "symbol": "BTCUSDT",
            "strategy": signals[0] if signals else None,
            "state": asdict(self.repository.state()),
        }

    async def run(self):
        client = self.binance or BinanceClient(self.config)
        try:
            now = await client.server_time()
            at = now.replace(minute=now.minute // 15 * 15, second=0, microsecond=0)
            latest = await asyncio.to_thread(self.repository.signals, 1)
            previous = latest[0]["evaluated_at"] if latest else None
            first = previous + timedelta(minutes=15) if previous else at
            if first > at:
                return {"evaluated_at": at.isoformat(), "action": "already_evaluated", "evaluations": 0}
            # Fetch each native interval window once, including earliest evaluation warmup.
            count = int((at - first) / timedelta(minutes=15)) + 1
            quarter, hourly = await asyncio.gather(
                client.klines(interval="15m", end=at, limit=99 + count),
                client.klines(
                    interval="1h",
                    end=at.replace(minute=0),
                    limit=200 + int((at.replace(minute=0) - first.replace(minute=0)) / timedelta(hours=1)),
                ),
            )
            completed = 0
            action = "already_evaluated"
            for index in range(count):
                evaluation_at = first + timedelta(minutes=15 * index)
                # Identical rolling warmup to a task that ran at the original close; no future bars.
                q = contiguous_tail([bar for bar in quarter if bar.closed and bar.close_time <= evaluation_at][-100:])
                h = contiguous_tail(
                    [bar for bar in hourly if bar.closed and bar.close_time <= evaluation_at.replace(minute=0)][-200:]
                )
                if not q or q[-1].close_time != evaluation_at:
                    raise ValueError("Latest closed Binance 15m candle is unavailable")
                if len(q) < 21 or len(h) < 50 or h[-1].close_time != evaluation_at.replace(minute=0):
                    raise ValueError("Binance strategy history is incomplete")
                snapshot = await asyncio.to_thread(
                    self.repository.evaluate_once, evaluation_at, lambda state: evaluate(q, h, evaluation_at, state)
                )
                if snapshot:
                    completed += 1
                    action = snapshot["action"]
            return {"evaluated_at": at.isoformat(), "action": action, "evaluations": completed}
        finally:
            if self.binance is None:
                await client.close()
