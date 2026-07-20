"""Market-specific daily provider ordering, retry, batching, and gap fallback."""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import date
from typing import Any, Callable, Iterable

import pandas as pd

from finance_analysis.integrations.market_data.config import DataProviderConfig, get_data_provider_config
from finance_analysis.integrations.market_data.history import HistoricalProviderError

from .models import ProviderBars, RoutedAdjustment, RoutedBars
from .validator import missing_daily_days, validate_daily_bars

logger = logging.getLogger(__name__)

MARKET_PROVIDER_PRIORITY = {
    "CN": {"EfinanceFetcher": 300, "AkshareFetcher": 200, "LongbridgeFetcher": 100},
    "HK": {"AkshareFetcher": 300, "EfinanceFetcher": 200, "LongbridgeFetcher": 100},
    "US": {"YfinanceFetcher": 300, "LongbridgeFetcher": 100},
}


def default_providers(market: str) -> list[Any]:
    from finance_analysis.integrations.market_data.providers.akshare import AkshareFetcher
    from finance_analysis.integrations.market_data.providers.efinance import EfinanceFetcher
    from finance_analysis.integrations.market_data.providers.longbridge.market import LongbridgeFetcher
    from finance_analysis.integrations.market_data.providers.yfinance import YfinanceFetcher

    return {
        "CN": [EfinanceFetcher(), AkshareFetcher(), LongbridgeFetcher()],
        "HK": [AkshareFetcher(), EfinanceFetcher(), LongbridgeFetcher()],
        "US": [YfinanceFetcher(), LongbridgeFetcher()],
    }[market]


class MarketDataProviderRouter:
    def __init__(
        self,
        market: str,
        providers: Iterable[Any] | None = None,
        *,
        config: DataProviderConfig | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.market = str(market).upper()
        if self.market not in MARKET_PROVIDER_PRIORITY:
            raise ValueError(f"Unsupported market={market}; expected CN, HK, or US")
        self.config = config or get_data_provider_config()
        self.providers = tuple(providers or default_providers(self.market))
        self._sleep = sleep
        self._semaphores = {
            provider.name: threading.BoundedSemaphore(self._concurrency(provider.name))
            for provider in self.providers
        }
        self._daily_batch: dict[str, pd.DataFrame] = {}
        self._daily_batch_prepared = False
        self._daily_batch_error = ""
        self._adjustment_batch: dict[str, Any] = {}
        self._adjustment_batch_prepared = False
        self._adjustment_batch_error = ""

    def prepare_batches(
        self,
        symbols: list[Any],
        daily_days: list[date],
        adjustment_days: list[date],
    ) -> None:
        if not symbols:
            return
        first = self.providers[0]
        if daily_days and hasattr(first, "fetch_daily_bars_batch"):
            self._daily_batch_prepared = True
            try:
                self._daily_batch = self._call(
                    first,
                    "daily_batch",
                    lambda: first.fetch_daily_bars_batch(symbols, min(daily_days), max(daily_days)),
                )
            except Exception as exc:
                self._daily_batch_error = f"{first.name} batch: {str(exc)[:240]}"
                logger.exception("market=%s provider=%s data_type=daily_batch failed", self.market, first.name)
        if adjustment_days and hasattr(first, "fetch_adjustment_data_batch"):
            self._adjustment_batch_prepared = True
            try:
                self._adjustment_batch = self._call(
                    first,
                    "adjustment_batch",
                    lambda: first.fetch_adjustment_data_batch(symbols, adjustment_days),
                )
            except Exception as exc:
                self._adjustment_batch_error = f"{first.name} batch: {str(exc)[:240]}"
                logger.exception("market=%s provider=%s data_type=adjustment_batch failed", self.market, first.name)

    def fetch_daily(self, symbol: Any, requested_days: list[date]) -> RoutedBars:
        if not requested_days:
            return RoutedBars([], [], [], "empty")
        missing = list(requested_days)
        batches: list[ProviderBars] = []
        providers_used: list[str] = []
        fallback_reasons: list[str] = []
        for index, provider in enumerate(self.providers):
            if not missing:
                break
            target = list(missing)
            try:
                if index == 0 and self._daily_batch_prepared and not self._daily_batch_error:
                    frame = self._daily_batch.get(symbol.code, pd.DataFrame())
                elif index == 0 and self._daily_batch_error:
                    raise RuntimeError(self._daily_batch_error)
                else:
                    frame = self._call(
                        provider,
                        "daily",
                        lambda p=provider: p.fetch_daily_bars(symbol, min(target), max(target)),
                    )
                rows = validate_daily_bars(frame, target)
            except Exception as exc:
                fallback_reasons.append(f"{provider.name}: {str(exc)[:240]}")
                logger.warning(
                    "market=%s code=%s provider=%s data_type=daily reason=%s",
                    self.market,
                    symbol.code,
                    provider.name,
                    exc,
                )
                continue
            missing_set = set(missing)
            rows = [row for row in rows if row["date"] in missing_set]
            if rows:
                priority = MARKET_PROVIDER_PRIORITY[self.market][provider.name]
                batches.append(ProviderBars(provider.name, priority, rows))
                providers_used.append(provider.name)
            missing = missing_daily_days(
                [row for batch in batches for row in batch.rows],
                requested_days,
            )
            if missing:
                fallback_reasons.append(f"{provider.name}: incomplete daily range, missing={len(missing)}")
        return RoutedBars(
            batches,
            missing,
            providers_used,
            f"{min(requested_days)}..{max(requested_days)}",
            fallback_reasons,
        )

    def fetch_adjustment(self, symbol: Any, requested_days: list[date]) -> RoutedAdjustment:
        fallback_reasons: list[str] = []
        for index, provider in enumerate(self.providers):
            if not hasattr(provider, "fetch_adjustment_data") and not (
                index == 0 and hasattr(provider, "fetch_adjustment_data_batch")
            ):
                continue
            try:
                if index == 0 and self._adjustment_batch_prepared and not self._adjustment_batch_error:
                    data = self._adjustment_batch.get(symbol.code)
                elif index == 0 and self._adjustment_batch_error:
                    raise RuntimeError(self._adjustment_batch_error)
                else:
                    data = self._call(
                        provider,
                        "adjustment",
                        lambda p=provider: p.fetch_adjustment_data(symbol, requested_days),
                    )
                if data is None:
                    raise RuntimeError("provider returned no adjustment payload")
                return RoutedAdjustment(provider.name, data, fallback_reasons)
            except Exception as exc:
                fallback_reasons.append(f"{provider.name}: {str(exc)[:240]}")
                logger.warning(
                    "market=%s code=%s provider=%s data_type=adjustment reason=%s",
                    self.market,
                    symbol.code,
                    provider.name,
                    exc,
                )
        return RoutedAdjustment(None, None, fallback_reasons)

    def _concurrency(self, provider_name: str) -> int:
        if provider_name == "LongbridgeFetcher":
            return min(5, max(1, self.config.market_data_longbridge_max_concurrency))
        if provider_name == "YfinanceFetcher":
            return max(1, self.config.market_data_yfinance_max_concurrency)
        return 1

    def _retries(self, provider_name: str) -> int:
        if provider_name == "LongbridgeFetcher":
            return max(0, self.config.market_data_longbridge_max_retries)
        if provider_name == "YfinanceFetcher":
            return max(0, self.config.market_data_yfinance_max_retries)
        return 1

    def _call(self, provider: Any, data_type: str, callback: Callable[[], Any]):
        attempts = self._retries(provider.name) + 1
        for attempt in range(attempts):
            try:
                with self._semaphores[provider.name]:
                    return callback()
            except Exception as exc:
                if not self._is_retryable(exc) or attempt + 1 >= attempts:
                    raise
                delay = min(30.0, 0.5 * (2**attempt)) + random.uniform(0.0, 0.25)
                logger.warning(
                    "market=%s provider=%s data_type=%s retry=%s/%s delay=%.2fs reason=%s",
                    self.market,
                    provider.name,
                    data_type,
                    attempt + 1,
                    attempts - 1,
                    delay,
                    exc,
                )
                self._sleep(delay)
        raise AssertionError("unreachable provider retry loop")

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, HistoricalProviderError):
            return exc.retryable
        text = str(exc).lower()
        if any(token in text for token in ("auth", "credential", "permission", "forbidden")):
            return False
        return isinstance(exc, (ConnectionError, TimeoutError)) or any(
            token in text for token in ("429", "rate limit", "timeout", "temporarily", "connection")
        )


__all__ = ["MARKET_PROVIDER_PRIORITY", "MarketDataProviderRouter", "default_providers"]
