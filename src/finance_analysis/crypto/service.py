"""BTC strategy reads and scheduled evaluation; market data is never persisted."""

import asyncio
from dataclasses import asdict
from datetime import timedelta

from finance_analysis.crypto.config import get_crypto_config
from finance_analysis.crypto.features import contiguous_tail
from finance_analysis.crypto.registry import STRATEGIES, SYMBOL
from finance_analysis.integrations.crypto.binance import BinanceClient


class CryptoService:
    def __init__(self, repository=None, binance=None, config=None, definitions=STRATEGIES):
        self.definitions = definitions
        self.config = config or get_crypto_config()
        if repository is None:
            from finance_analysis.database.repositories.crypto import CryptoRepository

            repository = CryptoRepository()
        self.repository = repository
        self.binance = binance

    def definition(self, strategy_key):
        return next((item for item in self.definitions if item.key == strategy_key), None)

    def get_signals(self, strategy_key, symbol, limit=50, **filters):
        return self.repository.signals(strategy_key, symbol, limit, **filters)

    def get_performance(self, strategy_key, symbol):
        from finance_analysis.crypto.performance import performance

        result = performance(
            self.repository.signals(strategy_key, symbol, None), self.repository.state(strategy_key, symbol)
        )
        return dict(
            result, strategy_key=strategy_key, symbol=symbol, display_name=self.definition(strategy_key).display_name
        )

    def get_overview(self, strategy_key, symbol):
        signals = self.get_signals(strategy_key, symbol, 1)
        return {
            "strategy_key": strategy_key,
            "symbol": symbol,
            "strategy": signals[0] if signals else None,
            "state": asdict(self.repository.state(strategy_key, symbol)),
        }

    def get_strategies(self):
        items = []
        for definition in self.definitions:
            info = self.get_overview(definition.key, SYMBOL)
            latest = info["strategy"]
            items.append(
                dict(
                    strategy_key=definition.key,
                    display_name=definition.display_name,
                    enabled=definition.enabled,
                    current_position=info["state"]["position_pct"],
                    latest_action=latest["action"] if latest else None,
                    latest_evaluated_at=latest["evaluated_at"] if latest else None,
                )
            )
        return items

    async def run(self):
        client = self.binance or BinanceClient(self.config)
        try:
            now = await client.server_time()
            at = now.replace(minute=now.minute // 15 * 15, second=0, microsecond=0)
            plans = []
            for definition in self.definitions:
                if not definition.enabled:
                    continue
                previous = await asyncio.to_thread(self.repository.latest_snapshot_time, definition.key, SYMBOL)
                first = previous + timedelta(minutes=15) if previous else at
                plans.append((definition, first))
            pending = [first for _, first in plans if first <= at]
            if not pending:
                return {"evaluated_at": at.isoformat(), "strategies": [], "evaluations": 0}
            first = min(pending)
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
            results, failures = [], []
            for definition, first in plans:
                completed, action = 0, "already_evaluated"
                try:
                    evaluation_at = first
                    while evaluation_at <= at:
                        q = contiguous_tail(
                            [bar for bar in quarter if bar.closed and bar.close_time <= evaluation_at][-100:]
                        )
                        h = contiguous_tail(
                            [bar for bar in hourly if bar.closed and bar.close_time <= evaluation_at.replace(minute=0)][
                                -200:
                            ]
                        )
                        if not q or q[-1].close_time != evaluation_at:
                            raise ValueError("Latest closed Binance 15m candle is unavailable")
                        if len(q) < 21 or len(h) < 50 or h[-1].close_time != evaluation_at.replace(minute=0):
                            raise ValueError("Binance strategy history is incomplete")
                        snapshot = await asyncio.to_thread(
                            self.repository.evaluate_once,
                            definition.key,
                            SYMBOL,
                            evaluation_at,
                            lambda state: definition.evaluate(q, h, evaluation_at, state),
                        )
                        if snapshot:
                            completed += 1
                            action = snapshot["action"]
                        evaluation_at += timedelta(minutes=15)
                except Exception as error:
                    failures.append((definition.key, error))
                results.append(dict(strategy_key=definition.key, action=action, evaluations=completed))
            if failures:
                raise ValueError(
                    "Strategy evaluation failed: " + ", ".join(f"{key}: {error}" for key, error in failures)
                ) from failures[0][1]
            return {
                "evaluated_at": at.isoformat(),
                "strategies": results,
                "evaluations": sum(item["evaluations"] for item in results),
            }
        finally:
            if self.binance is None:
                await client.close()
