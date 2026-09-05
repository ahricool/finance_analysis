"""Unified market-scoped forward-adjusted daily OHLCV synchronization."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any

from finance_analysis.database.repositories.stock import StockRepository
from finance_analysis.database.repositories.universe import UniverseResolver
from finance_analysis.integrations.market_data.config import (
    DataProviderConfig,
    get_data_provider_config,
)
from finance_analysis.integrations.market_data.models import BatchBarResult
from finance_analysis.integrations.market_data.service import MarketDataService
from finance_analysis.market_review.trading_calendar import get_completed_trading_days, get_trading_days_between

from .models import DailyResult, SymbolResult, normalize_sync_mode

logger = logging.getLogger(__name__)
MAX_RESULT_ITEMS = 20
ADJUSTMENT_SCALE_MIN_DATES = 3
ADJUSTMENT_SCALE_MIN_CHANGE = 0.003
ADJUSTMENT_SCALE_MAX_DRIFT = 0.005


class MarketDataSyncError(RuntimeError):
    pass


class MarketDataSyncService:
    def __init__(
        self,
        market: str,
        *,
        stock_repository: StockRepository | None = None,
        universe_resolver: UniverseResolver | None = None,
        market_data_service: MarketDataService | None = None,
        config: DataProviderConfig | None = None,
        now: datetime | None = None,
        sync_mode: str = "incremental",
    ):
        self.market = str(market).strip().upper()
        if self.market not in {"CN", "US"}:
            raise ValueError(f"Unsupported market={market}; market_data_sync currently supports CN or US")
        self.config = config or get_data_provider_config()
        self.stock_repository = stock_repository or StockRepository()
        self.universe_resolver = universe_resolver or UniverseResolver()
        self.market_data = market_data_service or MarketDataService(config=self.config)
        self.now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self.sync_mode = normalize_sync_mode(sync_mode)

    def run(self) -> dict[str, Any]:
        symbols = self.load_scope()
        if not symbols:
            raise MarketDataSyncError(f"No enabled daily symbols in the {self.market} synchronization scope")
        full_days = self._refresh_days(self.config.market_data_initial_daily_days)
        daily_days_by_code: dict[str, list[date]] = {}
        for symbol in symbols:
            has_history = self.stock_repository.has_daily_data(symbol.id) if self.sync_mode == "incremental" else False
            natural_days = (
                self.config.market_data_refresh_daily_days
                if self.sync_mode == "incremental" and has_history
                else self.config.market_data_initial_daily_days
            )
            daily_days_by_code[symbol.code] = self._refresh_days(natural_days)
        logger.info(
            "market=%s job=market_data_sync sync_mode=%s symbol_count=%s initial_days=%s refresh_days=%s "
            "adjustment=forward",
            self.market,
            self.sync_mode,
            len(symbols),
            self.config.market_data_initial_daily_days,
            self.config.market_data_refresh_daily_days,
        )
        daily_results = self._sync_daily_batch_groups(symbols, daily_days_by_code, full_days=full_days)
        results = [
            SymbolResult(
                symbol.code,
                daily_results.get(symbol.code, DailyResult("failed", reason="daily result missing")),
            )
            for symbol in symbols
        ]
        summary = self._summarize(
            results,
            len(symbols),
        )
        if summary["success_symbols"] + summary["partial_symbols"] == 0:
            raise MarketDataSyncError(f"All {len(symbols)} {self.market} symbols failed; see task log")
        return summary

    def load_scope(self) -> list[Any]:
        """Resolve the explicit system-owned daily synchronization universe."""
        key = "cn_daily_sync" if self.market == "CN" else "us_daily_sync"
        return [
            instrument
            for instrument in self.universe_resolver.resolve_universe(key)
            if instrument.market == self.market and instrument.listing_status == "ACTIVE"
        ]

    def _refresh_days(self, natural_days: int) -> list[date]:
        end = get_completed_trading_days(self.market.lower(), 1, self.now)[-1]
        start = end - timedelta(days=natural_days - 1)
        return get_trading_days_between(self.market.lower(), start, end)

    def _sync_daily(self, symbol: Any, requested_days: list[date]) -> DailyResult:
        try:
            routed = self.market_data.get_daily_bars(
                [symbol.code],
                min(requested_days),
                max(requested_days),
                adjustment="forward",
                source_policy="remote_only",
            )
        except Exception as exc:
            logger.exception("market=%s code=%s daily fetch failed", self.market, symbol.code)
            return DailyResult("failed", reason=str(exc))
        return self._persist_daily_result(
            symbol, requested_days, routed, replace_history=getattr(self, "sync_mode", "incremental") == "full"
        )

    def _sync_daily_batch_groups(
        self,
        symbols: list[Any],
        daily_days_by_code: dict[str, list[date]],
        *,
        full_days: list[date] | None = None,
    ) -> dict[str, DailyResult]:
        groups: dict[tuple[date, date], list[Any]] = defaultdict(list)
        for symbol in symbols:
            requested_days = daily_days_by_code[symbol.code]
            groups[(min(requested_days), max(requested_days))].append(symbol)
        logger.info(
            "market=%s data_type=daily symbol_count=%s batch_group_count=%s",
            self.market,
            len(symbols),
            len(groups),
        )

        results: dict[str, DailyResult] = {}
        automatic_full_symbols: list[Any] = []
        replace_fetched_history = getattr(self, "sync_mode", "incremental") == "full"
        for (start_date, end_date), grouped_symbols in groups.items():
            codes = [symbol.code for symbol in grouped_symbols]
            logger.info(
                "market=%s data_type=daily action=batch_fetch symbol_count=%s start_date=%s end_date=%s sample=%s",
                self.market,
                len(codes),
                start_date,
                end_date,
                codes[:5],
            )
            try:
                routed = self.market_data.get_daily_bars(
                    codes,
                    start_date,
                    end_date,
                    adjustment="forward",
                    source_policy="remote_only",
                )
            except Exception as exc:
                logger.exception(
                    "market=%s data_type=daily batch fetch failed symbol_count=%s start_date=%s end_date=%s",
                    self.market,
                    len(codes),
                    start_date,
                    end_date,
                )
                routed = BatchBarResult(failed_symbols={code: str(exc) or type(exc).__name__ for code in codes})
            if self.market == "US" and not replace_fetched_history:
                routed = self._recover_us_daily_gaps(
                    routed,
                    {symbol.code: daily_days_by_code[symbol.code] for symbol in grouped_symbols},
                )
            for symbol in grouped_symbols:
                bars = routed.data.get(symbol.code, [])
                requested_days = daily_days_by_code[symbol.code]
                is_incremental_window = bool(
                    full_days
                    and self.sync_mode == "incremental"
                    and (min(requested_days), max(requested_days)) != (min(full_days), max(full_days))
                )
                if is_incremental_window and bars and self._has_adjustment_scale_change(symbol, bars):
                    automatic_full_symbols.append(symbol)
                    logger.warning(
                        "market=%s code=%s daily adjustment scale changed; upgrading to full refresh",
                        self.market,
                        symbol.code,
                    )
                    continue
                results[symbol.code] = self._persist_daily_result(
                    symbol,
                    requested_days,
                    routed,
                    replace_history=replace_fetched_history,
                )

        if automatic_full_symbols and full_days:
            codes = [symbol.code for symbol in automatic_full_symbols]
            try:
                routed = self.market_data.get_daily_bars(
                    codes,
                    min(full_days),
                    max(full_days),
                    adjustment="forward",
                    source_policy="remote_only",
                )
            except Exception as exc:
                logger.exception(
                    "market=%s data_type=daily automatic full refresh failed symbol_count=%s",
                    self.market,
                    len(codes),
                )
                routed = BatchBarResult(failed_symbols={code: str(exc) or type(exc).__name__ for code in codes})
            for symbol in automatic_full_symbols:
                result = self._persist_daily_result(symbol, full_days, routed, replace_history=True)
                result.automatic_full_refresh = True
                results[symbol.code] = result
        return results

    @staticmethod
    def _missing_daily_dates(
        routed: BatchBarResult,
        requested_days_by_code: dict[str, list[date]],
        observed_dates: set[date],
    ) -> dict[str, set[date]]:
        missing_by_code: dict[str, set[date]] = {}
        for code, requested_days in requested_days_by_code.items():
            bars = routed.data.get(code, [])
            if not bars:
                continue
            returned_dates = {bar.trade_date for bar in bars}
            first_returned = min(returned_dates)
            expected_dates = {day for day in requested_days if day in observed_dates and day >= first_returned}
            missing = expected_dates.difference(returned_dates)
            if missing:
                missing_by_code[code] = missing
        return missing_by_code

    @staticmethod
    def _merge_daily_gap_patch(
        routed: BatchBarResult,
        patch: BatchBarResult,
        missing_by_code: dict[str, set[date]],
    ) -> int:
        added = 0
        routed.request_errors.update(patch.request_errors)
        routed.request_errors.update(patch.failed_symbols)
        for code, missing_dates in missing_by_code.items():
            existing = {bar.trade_date: bar for bar in routed.data.get(code, [])}
            for bar in patch.data.get(code, []):
                if bar.trade_date in missing_dates and bar.trade_date not in existing:
                    existing[bar.trade_date] = bar
                    added += 1
            if not existing:
                continue
            routed.data[code] = [existing[trade_date] for trade_date in sorted(existing)]
            providers = list(dict.fromkeys(bar.provider for bar in routed.data[code]))
            routed.providers_used[code] = "+".join(providers)
            routed.failed_symbols.pop(code, None)
            if code in routed.missing_symbols:
                routed.missing_symbols.remove(code)
        return added

    def _recover_us_daily_gaps(
        self,
        routed: BatchBarResult,
        requested_days_by_code: dict[str, list[date]],
    ) -> BatchBarResult:
        """Retry cross-sectionally observable US daily gaps, then patch them with TickFlow."""
        observed_dates = {bar.trade_date for code in requested_days_by_code for bar in routed.data.get(code, [])}
        if not observed_dates:
            return routed
        max_retries = int(getattr(getattr(self, "config", None), "market_data_yfinance_max_retries", 2))
        missing_by_code = self._missing_daily_dates(routed, requested_days_by_code, observed_dates)
        for attempt in range(1, max_retries + 1):
            if not missing_by_code:
                break
            missing_dates = set().union(*missing_by_code.values())
            logger.warning(
                "market=US data_type=daily action=retry_gaps provider=yfinance attempt=%s symbol_count=%s "
                "missing_date_count=%s",
                attempt,
                len(missing_by_code),
                len(missing_dates),
            )
            try:
                patch = self.market_data.get_daily_bars(
                    sorted(missing_by_code),
                    min(missing_dates),
                    max(missing_dates),
                    adjustment="forward",
                    providers=("yfinance",),
                    source_policy="remote_only",
                )
            except Exception:
                logger.exception(
                    "market=US data_type=daily action=retry_gaps provider=yfinance attempt=%s failed",
                    attempt,
                )
                continue
            self._merge_daily_gap_patch(routed, patch, missing_by_code)
            missing_by_code = self._missing_daily_dates(routed, requested_days_by_code, observed_dates)
        if not missing_by_code:
            return routed
        missing_dates = set().union(*missing_by_code.values())
        logger.warning(
            "market=US data_type=daily action=fallback_gaps provider=tickflow symbol_count=%s " "missing_date_count=%s",
            len(missing_by_code),
            len(missing_dates),
        )
        try:
            patch = self.market_data.get_daily_bars(
                sorted(missing_by_code),
                min(missing_dates),
                max(missing_dates),
                adjustment="forward",
                providers=("tickflow",),
                source_policy="remote_only",
            )
        except Exception:
            logger.exception("market=US data_type=daily action=fallback_gaps provider=tickflow failed")
            return routed
        self._merge_daily_gap_patch(routed, patch, missing_by_code)
        return routed

    def _has_adjustment_scale_change(self, symbol: Any, bars: list[Any]) -> bool:
        """Detect a coherent historical price-scale shift in the incremental overlap."""
        load_closes = getattr(self.stock_repository, "daily_closes", None)
        if not callable(load_closes) or len(bars) < ADJUSTMENT_SCALE_MIN_DATES:
            return False
        dates = [bar.trade_date for bar in bars]
        stored = load_closes(symbol.id, min(dates), max(dates))
        ratios: list[float] = []
        for bar in sorted(bars, key=lambda item: item.trade_date):
            old_close = stored.get(bar.trade_date)
            if old_close is None or old_close <= 0 or bar.close <= 0:
                continue
            ratio = float(bar.close) / float(old_close)
            if abs(ratio - 1.0) < ADJUSTMENT_SCALE_MIN_CHANGE:
                break
            if ratios and abs(ratio / median(ratios) - 1.0) > ADJUSTMENT_SCALE_MAX_DRIFT:
                break
            ratios.append(ratio)
        return len(ratios) >= ADJUSTMENT_SCALE_MIN_DATES

    def _persist_daily_result(
        self,
        symbol: Any,
        requested_days: list[date],
        routed: BatchBarResult,
        *,
        replace_history: bool = False,
    ) -> DailyResult:
        try:
            failure = routed.request_errors.get(symbol.code) or routed.failed_symbols.get(symbol.code)
            if replace_history and failure:
                return DailyResult("failed", reason=f"full_fetch_failed: {failure}", fallback_reasons=[failure])
            bars = routed.data.get(symbol.code, [])
            if not bars:
                failure = routed.failed_symbols.get(symbol.code)
                return DailyResult(
                    "failed" if failure else "success",
                    reason="all daily providers failed" if failure else "provider returned empty history; unchanged",
                    fallback_reasons=[failure] if failure else [],
                )
            provider = routed.providers_used.get(symbol.code)
            if not provider:
                raise ValueError("daily provider attribution missing")
            providers = list(dict.fromkeys(bar.provider for bar in bars))
            source = providers[0] if len(providers) == 1 else "mixed"
            returned_dates = {bar.trade_date for bar in bars}
            missing = sorted(set(requested_days).difference(returned_dates))
            rows = []
            for bar in bars:
                rows.append(
                    {
                        "date": bar.trade_date,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "amount": bar.amount,
                        "data_source": bar.provider,
                    }
                )
            if replace_history:
                stats = self.stock_repository.replace_daily_history(symbol.id, rows, source)
            else:
                stats = self.stock_repository.upsert_daily(symbol.id, rows, source)
            return DailyResult(
                status="partial" if missing and not replace_history else "success",
                inserted_rows=stats.inserted_rows,
                updated_rows=stats.updated_rows,
                deleted_rows=getattr(stats, "deleted_rows", 0),
                providers=providers,
                missing_amount=any(bar.amount is None for bar in bars),
                reason=f"missing_trading_days={len(missing)}" if missing and not replace_history else "",
                fallback_reasons=[routed.failed_symbols[symbol.code]] if symbol.code in routed.failed_symbols else [],
            )
        except Exception as exc:
            logger.exception("market=%s code=%s daily persistence failed", self.market, symbol.code)
            return DailyResult("failed", reason=str(exc))

    def _summarize(
        self,
        results: list[SymbolResult],
        symbol_count: int,
    ) -> dict[str, Any]:
        statuses = {result.code: result.daily.status for result in results}
        fallback_reasons = [
            {"code": result.code, "reason": reason} for result in results for reason in result.daily.fallback_reasons
        ]
        failures = [
            {
                "code": result.code,
                "daily_reason": result.daily.reason,
            }
            for result in results
            if statuses[result.code] != "success"
        ]
        provider_counts = Counter(provider for result in results for provider in result.daily.providers)
        return {
            "sync_status": "partial" if failures else "success",
            "sync_mode": self.sync_mode,
            "market": self.market,
            "symbol_count": symbol_count,
            "success_symbols": sum(status == "success" for status in statuses.values()),
            "partial_symbols": sum(status == "partial" for status in statuses.values()),
            "failed_symbols": sum(status == "failed" for status in statuses.values()),
            "inserted_rows": sum(result.daily.inserted_rows for result in results),
            "updated_rows": sum(result.daily.updated_rows for result in results),
            "provider_counts": dict(provider_counts),
            "missing_amount_symbols": sorted(result.code for result in results if result.daily.missing_amount),
            "fallback_reasons": fallback_reasons[:MAX_RESULT_ITEMS],
            "fallback_reasons_truncated": len(fallback_reasons) > MAX_RESULT_ITEMS,
            "automatic_full_refresh_symbols": sorted(
                result.code for result in results if result.daily.automatic_full_refresh
            ),
            "deleted_daily_rows": sum(result.daily.deleted_rows for result in results),
            "failure_count": len(failures),
            "failures": failures[:MAX_RESULT_ITEMS],
            "failures_truncated": len(failures) > MAX_RESULT_ITEMS,
        }


__all__ = [
    "MarketDataSyncError",
    "MarketDataSyncService",
]
