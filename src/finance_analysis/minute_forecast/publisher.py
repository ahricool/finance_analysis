"""Batch opted-in live inputs for the isolated Apple GPU service."""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import datetime

import httpx
from finance_analysis.config.env_parsing import env_str
from finance_analysis.core.time import utc_now
from finance_analysis.minute_forecast.cache import publish_forecast
from finance_analysis.minute_forecast.evaluation import settle_forecasts
from finance_analysis.minute_forecast.models import (
    BATCH_SIZE, MINUTE_MS, PROTOCOL, ForecastSnapshot, ForecastWindow, InferenceResult,
)
from finance_analysis.minute_forecast.windows import millis, stock_window
from finance_analysis.stocks.markets import MarketType

logger = logging.getLogger(__name__)


def forecast_url() -> str:
    return (env_str("KRONOS_URL", "") or "").strip().rstrip("/")


def forecast_model() -> str:
    return env_str("KRONOS_MODEL", "small") or "small"


class ForecastPublisher:
    def __init__(self, redis, url: str, expected_model: str) -> None:
        self.redis = redis
        self.url = url
        self.expected_model = expected_model
        self.published: dict[str, int] = {}
        self.last_attempted: dict[str, int] = {}
        self.stock_evaluated_at: int | None = None
        self.retry_after = 0

    async def run(self, bars: Mapping, targets: Callable[[], Mapping[str, MarketType]]) -> None:
        from finance_analysis.database.repositories.minute_forecast import MinuteForecastPreferences

        preferences = MinuteForecastPreferences()
        async with httpx.AsyncClient(timeout=12, trust_env=False) as predictor:
            while True:
                try:
                    enabled = await asyncio.to_thread(preferences.enabled_symbols)
                    await self.tick(bars, targets(), predictor, utc_now(), enabled)
                except Exception:
                    logger.exception("分钟线推理批次失败")
                await asyncio.sleep(3)

    async def tick(self, bars, targets: Mapping[str, MarketType], predictor,
                   now: datetime, enabled: set[str]) -> None:
        minute = millis(now.replace(second=0, microsecond=0))
        anchor = minute - MINUTE_MS
        ready = millis(now) >= self.retry_after
        groups: dict[tuple[int, int], list[ForecastWindow]] = defaultdict(list)
        self.published = {symbol: value for symbol, value in self.published.items()
                          if symbol in targets and symbol in enabled}
        self.last_attempted = {symbol: value for symbol, value in self.last_attempted.items()
                               if symbol in targets and symbol in enabled}
        for symbol, market in (targets.items() if ready else ()):
            if symbol not in enabled or not bars.get(symbol) or self.published.get(symbol) == minute:
                continue
            try:
                window = stock_window(symbol, market, bars[symbol], now)
            except (ArithmeticError, ValueError):
                continue  # An invalid bar on one security must not block the remaining symbols.
            if window is not None:
                groups[len(window.bars), len(window.targets)].append(window)

        def last_attempt(window: ForecastWindow) -> int:
            return self.last_attempted.get(window.symbol, 0)

        batches = []
        for windows in groups.values():
            windows.sort(key=last_attempt)
            batches.extend(windows[start:start + BATCH_SIZE] for start in range(0, len(windows), BATCH_SIZE))
        for batch in sorted(batches, key=lambda windows: last_attempt(windows[0])):
            if millis(utc_now()) >= minute + MINUTE_MS:
                break
            for window in batch:
                self.last_attempted[window.symbol] = minute
            if not await self.infer(predictor, batch):
                break
        if self.stock_evaluated_at != anchor and now.second >= 5:
            await settle_forecasts(self.redis, bars, targets, now)
            self.stock_evaluated_at = anchor

    async def infer(self, predictor, windows: list[ForecastWindow], *, track_accuracy: bool = True) -> bool:
        remaining = (windows[0].targets[0] + MINUTE_MS - millis(utc_now())) / 1000
        if remaining <= 0:
            return False
        try:
            async with asyncio.timeout(remaining):
                response = await predictor.post(f"{self.url}/predict", json={
                    "protocol": PROTOCOL, "windows": [window.model_dump(mode="json") for window in windows],
                })
            response.raise_for_status()
            result = InferenceResult.model_validate_json(response.content)
            if result.protocol != PROTOCOL or result.model != self.expected_model:
                raise ValueError("incompatible Kronos model or protocol")
        except TimeoutError:
            return False
        except (httpx.HTTPError, ValueError) as error:
            if not self.retry_after:
                logger.warning("Kronos 推理暂不可用: %s", error)
            self.retry_after = millis(utc_now()) + 10_000
            return False
        self.retry_after = 0
        by_symbol = {window.symbol: window for window in windows}
        generated_at = millis(utc_now())
        for prediction in result.predictions:
            window = by_symbol.pop(prediction.symbol, None)
            if window is None or [bar.timestamp for bar in prediction.bars] != window.targets:
                continue
            # Publish only a batch for the currently forming target minute. A
            # delayed result must never appear as though it was available live.
            if generated_at >= window.targets[0] + MINUTE_MS:
                continue
            last = window.bars[-1]
            await publish_forecast(self.redis, ForecastSnapshot(
                model=result.model, weights_revision=result.weights_revision, symbol=window.symbol,
                anchor=last.timestamp, anchor_close=last.close, generated_at=generated_at,
                lookback=len(window.bars), bars=prediction.bars,
                session_close=window.session_close,
            ), track_accuracy=track_accuracy)
            self.published[window.symbol] = window.targets[0]
        return True
