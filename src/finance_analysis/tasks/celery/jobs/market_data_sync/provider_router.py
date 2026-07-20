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
from .validator import enrich_daily_vwap, missing_daily_days, validate_daily_bars

logger = logging.getLogger(__name__)

MARKET_PROVIDER_PRIORITY = {
    "CN": {"EfinanceFetcher": 300, "AkshareFetcher": 200, "LongbridgeFetcher": 100},
    "HK": {"AkshareFetcher": 300, "EfinanceFetcher": 200, "LongbridgeFetcher": 100},
    "US": {"YfinanceFetcher": 400, "LongbridgeFetcher": 300},
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
            provider.name: threading.BoundedSemaphore(self._concurrency(provider.name)) for provider in self.providers
        }
        self._daily_batches: dict[str, dict[str, pd.DataFrame]] = {}
        self._daily_batch_errors: dict[str, dict[str, str]] = {}
        self._daily_batch_prepared_codes: dict[str, set[str]] = {}
        self._adjustment_batches: dict[str, dict[str, Any]] = {}
        self._adjustment_batch_errors: dict[str, str] = {}

    def prepare_batches(
        self,
        symbols: list[Any],
        daily_days_by_code: dict[str, list[date]],
        adjustment_days: list[date],
    ) -> None:
        if not symbols:
            return
        self._daily_batches.clear()
        self._daily_batch_errors.clear()
        self._daily_batch_prepared_codes.clear()
        self._adjustment_batches.clear()
        self._adjustment_batch_errors.clear()
        for provider in self.providers:
            if hasattr(provider, "fetch_daily_bars_batch"):
                self._prepare_daily_batch(provider, symbols, daily_days_by_code)
            if adjustment_days and hasattr(provider, "fetch_adjustment_data_batch"):
                try:
                    self._adjustment_batches[provider.name] = self._call(
                        provider,
                        "adjustment_batch",
                        lambda p=provider: p.fetch_adjustment_data_batch(symbols, adjustment_days),
                    )
                except Exception as exc:
                    self._adjustment_batch_errors[provider.name] = f"{provider.name} batch: {str(exc)[:240]}"
                    logger.exception(
                        "market=%s provider=%s data_type=adjustment_batch failed", self.market, provider.name
                    )

    def _prepare_daily_batch(
        self,
        provider: Any,
        symbols: list[Any],
        daily_days_by_code: dict[str, list[date]],
    ) -> None:
        grouped: dict[tuple[date, date], list[Any]] = {}
        for symbol in symbols:
            days = daily_days_by_code.get(symbol.code, [])
            if days:
                grouped.setdefault((min(days), max(days)), []).append(symbol)
        combined: dict[str, pd.DataFrame] = {}
        prepared_codes: set[str] = set()
        errors: dict[str, str] = {}
        for (start_date, end_date), group in grouped.items():
            try:
                combined.update(
                    self._call(
                        provider,
                        "daily_batch",
                        lambda p=provider, items=group, start=start_date, end=end_date: p.fetch_daily_bars_batch(
                            items, start, end
                        ),
                    )
                )
                prepared_codes.update(symbol.code for symbol in group)
            except Exception as exc:
                reason = f"{provider.name} batch: {str(exc)[:240]}"
                errors.update({symbol.code: reason for symbol in group})
                logger.exception("market=%s provider=%s data_type=daily_batch failed", self.market, provider.name)
        self._daily_batches[provider.name] = combined
        self._daily_batch_prepared_codes[provider.name] = prepared_codes
        self._daily_batch_errors[provider.name] = errors

    def fetch_daily(self, symbol: Any, requested_days: list[date]) -> RoutedBars:
        if not requested_days:
            return RoutedBars([], [], [], "empty")
        missing = list(requested_days)
        batches: list[ProviderBars] = []
        providers_used: list[str] = []
        fallback_reasons: list[str] = []
        for provider in self.providers:
            if not missing:
                break
            target = list(missing)
            try:
                provider_errors = self._daily_batch_errors.get(provider.name, {})
                if symbol.code in provider_errors:
                    raise RuntimeError(provider_errors[symbol.code])
                if symbol.code in self._daily_batch_prepared_codes.get(provider.name, set()):
                    frame = self._daily_batches[provider.name].get(symbol.code, pd.DataFrame())
                else:
                    frame = self._call(
                        provider,
                        "daily",
                        lambda p=provider: p.fetch_daily_bars(symbol, min(target), max(target)),
                    )
                invalid_reasons: list[str] = []
                rows = enrich_daily_vwap(
                    validate_daily_bars(frame, target, invalid_reasons=invalid_reasons),
                    provider.name,
                )
                if invalid_reasons:
                    reason = f"{provider.name}: discarded invalid daily rows={len(invalid_reasons)}"
                    fallback_reasons.append(reason)
                    logger.warning(
                        "market=%s code=%s provider=%s data_type=daily discarded_invalid_rows=%s reasons=%s",
                        self.market,
                        symbol.code,
                        provider.name,
                        len(invalid_reasons),
                        invalid_reasons[:10],
                    )
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
        for provider in self.providers:
            if (
                not hasattr(provider, "fetch_adjustment_data")
                and provider.name not in self._adjustment_batches
                and provider.name not in self._adjustment_batch_errors
            ):
                continue
            try:
                if provider.name in self._adjustment_batches:
                    data = self._adjustment_batches[provider.name].get(symbol.code)
                elif provider.name in self._adjustment_batch_errors:
                    raise RuntimeError(self._adjustment_batch_errors[provider.name])
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
