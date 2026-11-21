"""Batch all live inputs for the isolated Apple GPU service."""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import datetime

import httpx
from finance_analysis.config.env_parsing import env_str
from finance_analysis.core.time import utc_now
from finance_analysis.crypto.config import get_crypto_config
from finance_analysis.integrations.crypto.binance import BinanceClient
from finance_analysis.minute_forecast.cache import publish_forecast
from finance_analysis.minute_forecast.evaluation import settle_forecasts
from finance_analysis.minute_forecast.models import (
    BATCH_SIZE, BTC_SYMBOL, LOOKBACK, MINUTE_MS, PROTOCOL, ForecastSnapshot, ForecastWindow, InferenceResult,
)
from finance_analysis.minute_forecast.windows import btc_window, millis, stock_window
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
        self.btc_requested_at: datetime | None = None
        self.btc_input: ForecastWindow | None = None
        self.stock_evaluated_at: int | None = None
        self.btc_evaluated_at: int | None = None
        self.retry_after = 0

    async def run(self, bars: Mapping, targets: Callable[[], Mapping[str, MarketType]]) -> None:
        crypto = get_crypto_config()
        binance = BinanceClient(crypto)
        try:
            async with httpx.AsyncClient(timeout=12, trust_env=False) as predictor:
                while True:
                    try:
                        # Strategy enablement is unrelated to the BTC chart's public 1m feed.
                        await self.tick(bars, targets(), predictor, binance, utc_now())
                    except Exception:
                        logger.exception("分钟线推理批次失败")
                    await asyncio.sleep(3)
        finally:
            await binance.close()

    async def tick(self, bars, targets: Mapping[str, MarketType], predictor, binance,
                   now: datetime) -> None:
        minute = now.replace(second=0, microsecond=0)
        anchor = millis(minute) - MINUTE_MS
        ready = millis(now) >= self.retry_after
        groups: dict[tuple[int, int], list[ForecastWindow]] = defaultdict(list)
        self.published = {symbol: value for symbol, value in self.published.items()
                          if symbol in targets or (binance is not None and symbol == BTC_SYMBOL)}
        for symbol, market in (targets.items() if ready else ()):
            if not bars.get(symbol) or self.published.get(symbol) == anchor:
                continue
            try:
                window = stock_window(symbol, market, bars[symbol], now)
            except (ArithmeticError, ValueError):
                continue  # An invalid bar on one security must not block the remaining symbols.
            if window is not None:
                groups[len(window.bars), len(window.targets)].append(window)

        # BTC has an independent source. Start its fetch concurrently so a slow
        # Binance response cannot hold up the stock batches or subscription flow.
        btc_task = None
        if self.btc_input is not None and self.btc_input.bars[-1].timestamp != anchor:
            self.btc_input = None
        if (binance is not None and self.btc_input is None and now.second >= 3
                and (self.btc_requested_at is None or (now - self.btc_requested_at).total_seconds() >= 8)):
            self.btc_requested_at = now
            btc_task = asyncio.create_task(self.read_btc(binance, now))
        try:
            for windows in groups.values():
                for start in range(0, len(windows), BATCH_SIZE):
                    ready = await self.infer(predictor, windows[start:start + BATCH_SIZE])
                    if not ready:
                        break
                if not ready:
                    break
            if btc_task is not None:
                self.btc_input = await btc_task
            if ready and self.btc_input is not None and self.published.get(BTC_SYMBOL) != anchor:
                await self.infer(predictor, [self.btc_input])
            # Keep settlement moving during inference backoff. BTC can arrive
            # a tick later than the equity candles, so track its cadence separately.
            stock_due = self.stock_evaluated_at != anchor and now.second >= 5
            btc_due = self.btc_evaluated_at != anchor and self.btc_input is not None
            if stock_due or btc_due:
                await settle_forecasts(
                    self.redis, bars, targets if stock_due else {}, self.btc_input if btc_due else None, now,
                )
                if stock_due:
                    self.stock_evaluated_at = anchor
                if btc_due:
                    self.btc_evaluated_at = anchor
        finally:
            if btc_task is not None and not btc_task.done():
                btc_task.cancel()
                await asyncio.gather(btc_task, return_exceptions=True)

    async def read_btc(self, binance, now: datetime) -> ForecastWindow | None:
        try:
            async with asyncio.timeout(5):
                rows = await binance.spot_minute_rows(end=now, limit=LOOKBACK + 1)
            return btc_window(rows, now)
        except (TimeoutError, httpx.HTTPError, ValueError, TypeError):
            logger.warning("BTCUSDT 预测分钟线暂不可用", exc_info=True)
            return None

    async def infer(self, predictor, windows: list[ForecastWindow]) -> bool:
        if millis(utc_now()) >= windows[0].targets[0] + MINUTE_MS:
            return False
        try:
            response = await predictor.post(f"{self.url}/predict", json={
                "protocol": PROTOCOL, "windows": [window.model_dump(mode="json") for window in windows],
            })
            response.raise_for_status()
            result = InferenceResult.model_validate_json(response.content)
            if result.protocol != PROTOCOL or result.model != self.expected_model:
                raise ValueError("incompatible Kronos model or protocol")
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
            ))
            self.published[window.symbol] = last.timestamp
        return True
