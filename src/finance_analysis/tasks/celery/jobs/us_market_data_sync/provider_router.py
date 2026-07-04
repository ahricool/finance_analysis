"""Provider ordering, retry policy, validation, and gap-only fallback merging."""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Callable

from finance_analysis.integrations.market_data.history import HistoricalProviderError
from finance_analysis.market_review.trading_calendar import get_market_session_bounds

from .models import ProviderBars, RoutedBars
from .validator import (
    missing_daily_days,
    missing_minute_times,
    validate_daily_bars,
    validate_minute_bars,
)

logger = logging.getLogger(__name__)


class HistoricalProviderRouter:
    def __init__(
        self,
        longbridge,
        yfinance,
        *,
        longbridge_concurrency: int,
        longbridge_retries: int,
        yfinance_concurrency: int,
        yfinance_retries: int,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.providers = (longbridge, yfinance)
        self._semaphores = {
            longbridge.name: threading.BoundedSemaphore(min(5, max(1, longbridge_concurrency))),
            yfinance.name: threading.BoundedSemaphore(max(1, yfinance_concurrency)),
        }
        self._retries = {longbridge.name: max(0, longbridge_retries), yfinance.name: max(0, yfinance_retries)}
        self._sleep = sleep

    def fetch_daily(self, symbol, requested_days: list[date]) -> RoutedBars:
        if not requested_days:
            return RoutedBars([], [], [], "empty")
        start, end = min(requested_days), max(requested_days)
        missing = list(requested_days)
        batches: list[ProviderBars] = []
        providers_used: list[str] = []
        fallback_reasons: list[str] = []
        for provider in self.providers:
            if not missing:
                break
            target = list(missing)
            try:
                frame = self._call(
                    provider,
                    "daily",
                    lambda p=provider: p.fetch_daily_bars(symbol, min(target), max(target)),
                )
                rows = validate_daily_bars(frame, target)
            except Exception as exc:
                self._log_provider_failure(provider, symbol, "daily", f"{min(target)}..{max(target)}", exc)
                fallback_reasons.append(f"{provider.name}: {str(exc)[:240]}")
                continue
            if rows:
                batches.append(ProviderBars(provider.name, provider.source_priority, rows))
                providers_used.append(provider.name)
            missing = missing_daily_days(
                [row for batch in batches for row in batch.rows],
                requested_days,
            )
            if missing and provider is self.providers[0]:
                fallback_reasons.append(f"{provider.name}: incomplete daily range, missing={len(missing)}")
        return RoutedBars(batches, missing, providers_used, f"{start}..{end}", fallback_reasons)

    def fetch_minute_day(self, symbol, trading_day: date, *, now: datetime | None = None) -> RoutedBars:
        session_open, session_close = get_market_session_bounds("us", trading_day)
        start = session_open.astimezone(timezone.utc)
        end = session_close.astimezone(timezone.utc)
        batches: list[ProviderBars] = []
        providers_used: list[str] = []
        missing: list[datetime] | None = None
        existing_times: set[datetime] = set()
        fallback_reasons: list[str] = []
        for provider in self.providers:
            if missing == []:
                break
            try:
                frame = self._call(
                    provider,
                    "minute",
                    lambda p=provider: p.fetch_minute_bars(symbol, start, end, session_type="regular"),
                )
                rows = validate_minute_bars(frame, trading_day, now=now)
            except Exception as exc:
                self._log_provider_failure(provider, symbol, "minute", f"{start.isoformat()}..{end.isoformat()}", exc)
                fallback_reasons.append(f"{provider.name}: {str(exc)[:240]}")
                continue
            # Lower-priority fallback contributes gaps only and can never replace
            # an already validated Longbridge minute.
            rows = [row for row in rows if row["bar_time"] not in existing_times]
            if missing is not None:
                missing_set = set(missing)
                rows = [row for row in rows if row["bar_time"] in missing_set]
            if rows:
                batches.append(ProviderBars(provider.name, provider.source_priority, rows))
                providers_used.append(provider.name)
                existing_times.update(row["bar_time"] for row in rows)
            missing = missing_minute_times(
                [row for batch in batches for row in batch.rows],
                trading_day,
            )
            if missing and provider is self.providers[0]:
                fallback_reasons.append(f"{provider.name}: incomplete minute session, missing={len(missing)}")
        if missing is None:
            missing = missing_minute_times([], trading_day)
        return RoutedBars(
            batches, missing, providers_used, f"{start.isoformat()}..{end.isoformat()}", fallback_reasons
        )

    def _call(self, provider, data_type: str, callback: Callable[[], Any]):
        attempts = self._retries[provider.name] + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                with self._semaphores[provider.name]:
                    return callback()
            except Exception as exc:
                last_error = exc
                if not self._is_retryable(exc) or attempt + 1 >= attempts:
                    raise
                delay = min(30.0, 0.5 * (2**attempt)) + random.uniform(0.0, 0.25)
                logger.warning(
                    "provider=%s data_type=%s retry=%s/%s delay=%.2fs reason=%s",
                    provider.name, data_type, attempt + 1, attempts - 1, delay, exc,
                )
                self._sleep(delay)
        assert last_error is not None
        raise last_error

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, HistoricalProviderError):
            return exc.retryable
        error_code = getattr(exc, "code", None)
        if error_code in (301602, 301606):
            return True
        if error_code in (301600, 301604, 301607):
            return False
        text = str(exc).lower()
        if any(token in text for token in ("auth", "credential", "permission", "invalid parameter", "forbidden")):
            return False
        return isinstance(exc, (ConnectionError, TimeoutError)) or any(
            token in text for token in ("429", "rate limit", "timeout", "tempor", "connection closed", "context dropped")
        )

    @staticmethod
    def _log_provider_failure(provider, symbol, data_type: str, requested_range: str, exc: Exception) -> None:
        logger.warning(
            "market=%s code=%s provider=%s data_type=%s requested_range=%s reason=%s",
            symbol.market, symbol.code, provider.name, data_type, requested_range, exc,
            exc_info=True,
        )


__all__ = ["HistoricalProviderRouter"]
