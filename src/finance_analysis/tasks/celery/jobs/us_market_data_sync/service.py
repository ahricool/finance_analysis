"""Orchestration for database-configured US daily and one-minute synchronization."""

from __future__ import annotations

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from finance_analysis.database.repositories.stock import (
    MarketDataSymbolRepository,
    StockRepository,
    UpsertStats,
)
from finance_analysis.integrations.market_data.config import DataProviderConfig, get_data_provider_config
from finance_analysis.integrations.market_data.providers.longbridge.market import LongbridgeFetcher
from finance_analysis.integrations.market_data.providers.yfinance import YfinanceFetcher
from finance_analysis.market_review.trading_calendar import (
    get_completed_trading_days,
    get_trading_days_between,
)

from .models import DailyWindow, DataTypeResult, MinuteWindow, SymbolResult
from .provider_router import HistoricalProviderRouter
from .validator import expected_minute_times

logger = logging.getLogger(__name__)
NEW_YORK = ZoneInfo("America/New_York")
MAX_RESULT_FAILURES = 20


class USMarketDataSyncError(RuntimeError):
    pass


class USMarketDataSyncService:
    def __init__(
        self,
        *,
        symbol_repository: MarketDataSymbolRepository | None = None,
        stock_repository: StockRepository | None = None,
        router: HistoricalProviderRouter | None = None,
        config: DataProviderConfig | None = None,
        now: datetime | None = None,
    ):
        self.config = config or get_data_provider_config()
        self.symbol_repository = symbol_repository or MarketDataSymbolRepository()
        self.stock_repository = stock_repository or StockRepository()
        self.now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self.router = router or HistoricalProviderRouter(
            LongbridgeFetcher(),
            YfinanceFetcher(),
            longbridge_concurrency=self.config.market_data_longbridge_max_concurrency,
            longbridge_retries=self.config.market_data_longbridge_max_retries,
            yfinance_concurrency=self.config.market_data_yfinance_max_concurrency,
            yfinance_retries=self.config.market_data_yfinance_max_retries,
        )

    def run(self) -> dict[str, Any]:
        symbols = self.symbol_repository.list_enabled_symbols("US")
        if not symbols:
            raise USMarketDataSyncError("No enabled US market_data_symbol configuration")
        logger.info("market=US job=market_data_sync_us symbol_count=%s", len(symbols))
        max_workers = min(5, max(1, self.config.market_data_longbridge_max_concurrency))
        results: list[SymbolResult] = []
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="us-market-data") as executor:
            futures = {executor.submit(self._sync_symbol, symbol): symbol for symbol in symbols}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    logger.exception("market=US code=%s symbol synchronization failed: %s", symbol.code, exc)
                    failed = DataTypeResult("failed", "repair", reason=str(exc))
                    results.append(
                        SymbolResult(
                            code=symbol.code,
                            daily=failed if symbol.sync_daily else None,
                            minute=failed if symbol.sync_minute else None,
                        )
                    )
        summary = self._summarize(results, len(symbols))
        processed = sum(
            1
            for result in results
            if any(item and item.status in ("success", "partial") for item in (result.daily, result.minute))
        )
        if processed == 0:
            raise USMarketDataSyncError(f"All {len(symbols)} US symbols failed; see task log")
        return summary

    def _sync_symbol(self, symbol) -> SymbolResult:
        daily = self._sync_daily(symbol) if symbol.sync_daily else None
        minute = self._sync_minute(symbol) if symbol.sync_minute else None
        return SymbolResult(symbol.code, daily, minute)

    def _daily_window(self, symbol) -> DailyWindow:
        end = get_completed_trading_days("us", 1, self.now)[-1]
        if not self.stock_repository.has_daily_data(symbol.id):
            start = end - timedelta(days=self.config.market_data_initial_daily_days - 1)
            days = get_trading_days_between("us", start, end)
            return DailyWindow("bootstrap", start, end, tuple(days))
        days = get_completed_trading_days("us", self.config.market_data_repair_daily_days, self.now)
        return DailyWindow("repair", days[0], days[-1], tuple(days))

    def _minute_window(self, symbol) -> MinuteWindow:
        bootstrap = not self.stock_repository.has_minute_data(symbol.id)
        count = (
            self.config.market_data_initial_minute_days
            if bootstrap
            else self.config.market_data_repair_minute_days
        )
        return MinuteWindow(
            "bootstrap" if bootstrap else "repair",
            tuple(get_completed_trading_days("us", count, self.now)),
        )

    def _sync_daily(self, symbol) -> DataTypeResult:
        window = self._daily_window(symbol)
        requested = f"{window.start_date}..{window.end_date}"
        logger.info(
            "market=US code=%s provider=router data_type=daily requested_range=%s mode=%s",
            symbol.code, requested, window.mode,
        )
        try:
            routed = self.router.fetch_daily(symbol, list(window.trading_days))
            stats = UpsertStats()
            actual_dates: list[date] = []
            for batch in routed.batches:
                batch_stats = self.stock_repository.upsert_daily(
                    symbol.id, batch.rows, batch.provider, batch.priority
                )
                stats = self._add_stats(stats, batch_stats)
                actual_dates.extend(row["date"] for row in batch.rows)
            if not routed.batches:
                return DataTypeResult("failed", window.mode, requested_range=requested, reason="all providers failed")
            status = "partial" if routed.missing else "success"
            actual_range = f"{min(actual_dates)}..{max(actual_dates)}" if actual_dates else "empty"
            reason = (
                f"missing_trading_days={len(routed.missing)} actual_range={actual_range}"
                if routed.missing else ""
            )
            return DataTypeResult(
                status, window.mode, stats.inserted_rows, stats.updated_rows,
                stats.skipped_lower_priority_rows, routed.providers_used, requested,
                actual_range, reason,
                routed.fallback_reasons,
            )
        except Exception as exc:
            logger.exception(
                "market=US code=%s provider=router data_type=daily requested_range=%s mode=%s reason=%s",
                symbol.code, requested, window.mode, exc,
            )
            return DataTypeResult("failed", window.mode, requested_range=requested, reason=str(exc))

    def _sync_minute(self, symbol) -> DataTypeResult:
        window = self._minute_window(symbol)
        requested = f"{window.trading_days[0]}..{window.trading_days[-1]}"
        logger.info(
            "market=US code=%s provider=router data_type=minute requested_range=%s mode=%s",
            symbol.code, requested, window.mode,
        )
        stats = UpsertStats()
        providers: list[str] = []
        fallback_reasons: list[str] = []
        missing_count = 0
        successful_days = 0
        actual_times: list[datetime] = []
        for trading_day in window.trading_days:  # exactly one request unit per target day/provider
            try:
                routed = self.router.fetch_minute_day(symbol, trading_day, now=self.now)
                for batch in routed.batches:
                    batch_stats = self.stock_repository.upsert_minute(
                        symbol.id, batch.rows, batch.provider, batch.priority
                    )
                    stats = self._add_stats(stats, batch_stats)
                    actual_times.extend(row["bar_time"] for row in batch.rows)
                    if batch.provider not in providers:
                        providers.append(batch.provider)
                if routed.batches:
                    successful_days += 1
                missing_count += len(routed.missing)
                fallback_reasons.extend(routed.fallback_reasons)
            except Exception as exc:
                logger.exception(
                    "market=US code=%s provider=router data_type=minute requested_range=%s mode=%s reason=%s",
                    symbol.code, trading_day, window.mode, exc,
                )
                missing_count += len(expected_minute_times(trading_day))
        if successful_days == 0:
            return DataTypeResult("failed", window.mode, requested_range=requested, reason="all providers failed")
        status = "partial" if missing_count else "success"
        actual_range = "empty"
        if actual_times:
            actual_range = f"{min(actual_times).isoformat()}..{max(actual_times).isoformat()}"
        return DataTypeResult(
            status, window.mode, stats.inserted_rows, stats.updated_rows,
            stats.skipped_lower_priority_rows, providers, requested, actual_range,
            f"missing_minutes={missing_count} actual_range={actual_range}" if missing_count else "",
            fallback_reasons,
        )

    @staticmethod
    def _add_stats(left: UpsertStats, right: UpsertStats) -> UpsertStats:
        return UpsertStats(
            left.inserted_rows + right.inserted_rows,
            left.updated_rows + right.updated_rows,
            left.skipped_lower_priority_rows + right.skipped_lower_priority_rows,
        )

    def _summarize(self, results: list[SymbolResult], symbol_count: int) -> dict[str, Any]:
        failures: list[dict[str, str]] = []
        provider_counts: Counter[str] = Counter()
        modes: dict[str, set[str]] = {"bootstrap": set(), "repair": set()}

        def data_summary(data_type: str) -> dict[str, Any]:
            items = [(result.code, getattr(result, data_type)) for result in results]
            items = [(code, item) for code, item in items if item is not None]
            for code, item in items:
                modes[item.mode].add(code)
                for provider in item.providers:
                    provider_counts[provider] += 1
                if item.status in ("partial", "failed"):
                    logger.error(
                        "market=US code=%s provider=%s data_type=%s requested_range=%s status=%s reason=%s",
                        code, ",".join(item.providers) or "none", data_type,
                        item.requested_range, item.status, item.reason,
                    )
                    failures.append(
                        {
                            "code": code,
                            "data_type": data_type,
                            "provider": ",".join(item.providers) or "none",
                            "reason": item.reason[:300],
                        }
                    )
            return {
                "success_symbols": sum(item.status == "success" for _, item in items),
                "partial_symbols": sum(item.status == "partial" for _, item in items),
                "failed_symbols": sum(item.status == "failed" for _, item in items),
                "inserted_rows": sum(item.inserted_rows for _, item in items),
                "updated_rows": sum(item.updated_rows for _, item in items),
                "skipped_lower_priority_rows": sum(item.skipped_lower_priority_rows for _, item in items),
                "provider_counts": dict(Counter(p for _, item in items for p in item.providers)),
                "fallback_symbols": sum(bool(item.fallback_reasons) for _, item in items),
                "fallback_reasons": [
                    {"code": code, "reason": reason}
                    for code, item in items for reason in item.fallback_reasons
                ][:MAX_RESULT_FAILURES],
            }

        daily = data_summary("daily")
        minute = data_summary("minute")
        failure_count = len(failures)
        sync_status = "partial" if failure_count else "success"
        return {
            "sync_status": sync_status,
            "market": "US",
            "symbol_count": symbol_count,
            "bootstrap_symbol_count": len(modes["bootstrap"]),
            "repair_symbol_count": len(modes["repair"]),
            "daily": daily,
            "minute": minute,
            "failure_count": failure_count,
            "failures_truncated": failure_count > MAX_RESULT_FAILURES,
            "failures": failures[:MAX_RESULT_FAILURES],
        }


__all__ = ["USMarketDataSyncError", "USMarketDataSyncService"]
