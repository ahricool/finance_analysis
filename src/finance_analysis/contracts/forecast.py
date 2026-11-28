"""Forecast continuous UTC contract minutes from the elected streamer's closed candles."""
import asyncio
import logging
from collections import defaultdict

import httpx

from finance_analysis.contracts.service import key, now_ms, read_json
from finance_analysis.database.repositories.contracts import forecast_symbols
from finance_analysis.minute_forecast.models import (
    BATCH_SIZE, LIVE_HORIZON, LOOKBACK, MINUTE_MS, ObservedBar,
)
from finance_analysis.minute_forecast.publisher import ForecastPublisher, forecast_model
from finance_analysis.minute_forecast.windows import make_window

logger = logging.getLogger(__name__)


def contract_window(symbol, candles, minute):
    indexed = {bar["timestamp"]: bar for bar in candles if bar.get("closed") is True}
    bars = []
    for step in range(1, LOOKBACK + 1):
        candle = indexed.get(minute - step * MINUTE_MS)
        if candle is None:
            break
        bars.append(ObservedBar(**candle, amount=candle.get("turnover")))
    targets = [minute + step * MINUTE_MS for step in range(LIVE_HORIZON)]
    return make_window(symbol, "UTC", bars[::-1], minute - MINUTE_MS, targets)


async def run_contract_forecasts(redis, url):
    publisher = ForecastPublisher(redis, url, forecast_model())
    async with httpx.AsyncClient(timeout=12, trust_env=False) as predictor:
        while True:
            try:
                minute = now_ms() // MINUTE_MS * MINUTE_MS
                enabled = await asyncio.to_thread(forecast_symbols)
                groups = defaultdict(list)
                for symbol in enabled:
                    if publisher.published.get(symbol) == minute:
                        continue
                    candles = await read_json(redis, key(symbol, "minute"), [])
                    try:
                        window = contract_window(symbol, candles, minute)
                    except (KeyError, ValueError):
                        logger.warning("无效合约分钟线 %s", symbol)
                        continue
                    if window:
                        groups[len(window.bars)].append(window)
                for windows in groups.values():
                    for start in range(0, len(windows), BATCH_SIZE):
                        if now_ms() >= publisher.retry_after:
                            await publisher.infer(predictor, windows[start:start + BATCH_SIZE], track_accuracy=False)
            except Exception:
                logger.exception("合约分钟预测批次失败")
            await asyncio.sleep(8)
