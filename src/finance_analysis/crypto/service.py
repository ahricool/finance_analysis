"""BTC strategy reads and scheduled evaluation; market data is never persisted."""

import asyncio
from dataclasses import asdict

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

    def get_signals(self, limit=50):
        return self.repository.signals(limit)

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
            # Extra warmup stabilizes SMA-seeded EMA50 without fetching minute history.
            quarter, hourly = await asyncio.gather(
                client.klines(interval="15m", end=at, limit=100),
                client.klines(interval="1h", end=at.replace(minute=0), limit=200),
            )
            quarter = contiguous_tail([bar for bar in quarter if bar.closed and bar.close_time <= at])
            hourly = contiguous_tail([bar for bar in hourly if bar.closed and bar.close_time <= at.replace(minute=0)])
            if not quarter or quarter[-1].close_time != at:
                raise ValueError("Latest closed Binance 15m candle is unavailable")
            if len(quarter) < 21 or len(hourly) < 50 or hourly[-1].close_time != at.replace(minute=0):
                raise ValueError("Binance strategy history is incomplete")
            snapshot = await asyncio.to_thread(
                self.repository.evaluate_once, at, lambda state: evaluate(quarter, hourly, at, state)
            )
            return {"evaluated_at": at.isoformat(), "action": snapshot["action"] if snapshot else "already_evaluated"}
        finally:
            if self.binance is None:
                await client.close()
