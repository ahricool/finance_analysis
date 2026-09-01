"""Unified market-scoped forward-adjusted daily OHLCV synchronization."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any

from finance_analysis.database.repositories.stock import MarketDataSymbolRepository, StockRepository
from finance_analysis.integrations.market_data.config import (
    DataProviderConfig,
    get_data_provider_config,
    provider_order,
)
from finance_analysis.integrations.market_data.models import BatchBarResult
from finance_analysis.integrations.market_data.registry import INSTRUMENT_INFO
from finance_analysis.integrations.market_data.service import MarketDataService
from finance_analysis.market_review.trading_calendar import get_completed_trading_days, get_trading_days_between
from finance_analysis.stocks.market_scope import MarketDataScopeResolver

from .models import DailyResult, SymbolResult, normalize_sync_mode

logger = logging.getLogger(__name__)
MAX_RESULT_ITEMS = 20
REMOTE_INSTRUMENT_PROVIDERS = frozenset({"tickflow", "akshare"})
ADJUSTMENT_SCALE_MIN_DATES = 3
ADJUSTMENT_SCALE_MIN_CHANGE = 0.003
ADJUSTMENT_SCALE_MAX_DRIFT = 0.005
FULL_REFRESH_MIN_COVERAGE = 0.95


class MarketDataSyncError(RuntimeError):
    pass


class MarketDataSyncService:
    def __init__(
        self,
        market: str,
        *,
        symbol_repository: MarketDataSymbolRepository | None = None,
        stock_repository: StockRepository | None = None,
        watchlist_repository: Any = None,
        scope_resolver: MarketDataScopeResolver | None = None,
        market_data_service: MarketDataService | None = None,
        config: DataProviderConfig | None = None,
        now: datetime | None = None,
        sync_mode: str = "incremental",
    ):
        self.market = str(market).strip().upper()
        if self.market not in {"CN", "US"}:
            raise ValueError(f"Unsupported market={market}; market_data_sync currently supports CN or US")
        self.config = config or get_data_provider_config()
        self.symbol_repository = symbol_repository or MarketDataSymbolRepository()
        self.stock_repository = stock_repository or StockRepository()
        self.scope_resolver = scope_resolver or MarketDataScopeResolver(watchlist_repository)
        self.market_data = market_data_service or MarketDataService(config=self.config)
        self.now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self.sync_mode = normalize_sync_mode(sync_mode)
        self.unsupported_symbols: list[dict[str, str]] = []
        self.instrument_names_refreshed = 0
        self.instrument_name_failures: dict[str, str] = {}

    def run(self) -> dict[str, Any]:
        symbols = self.load_scope()
        if not symbols:
            if self.unsupported_symbols:
                return self._summarize([], 0)
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
        summary.update(
            {
                "instrument_names_refreshed": self.instrument_names_refreshed,
                "instrument_name_failure_count": len(self.instrument_name_failures),
            }
        )
        if summary["success_symbols"] + summary["partial_symbols"] == 0:
            raise MarketDataSyncError(f"All {len(symbols)} {self.market} symbols failed; see task log")
        return summary

    def load_scope(self) -> list[Any]:
        """Return the public shared scope, including calculation dependencies."""
        scope = self.scope_resolver.resolve(self.market)
        self.unsupported_symbols = list(scope.unsupported_symbols)
        strategy_records = self.scope_resolver.strategy_dependency_records(self.market)
        if strategy_records:
            # Strategy configuration owns daily readiness but must preserve a
            # watched ETF's independent minute-sync preference.
            self.symbol_repository.upsert_symbols(strategy_records, force_daily_sync=True)
        # A watched benchmark remains a watchlist symbol, so let the watchlist
        # record win while still inserting each canonical code only once.
        records_by_code = {record["code"]: record for record in self.scope_resolver.dependency_records(self.market)}
        records_by_code.update({record["code"]: record for record in strategy_records})
        records_by_code.update({record["code"]: record for record in scope.watchlist_records})
        records = [records_by_code[code] for code in sorted(records_by_code)]
        if records:
            self.symbol_repository.upsert_symbols(records, overwrite_runtime_flags=False)
        symbols = self.symbol_repository.list_enabled_daily_by_codes(
            self.market,
            scope.synchronization_codes,
        )
        self._refresh_instrument_names(symbols)
        return self.symbol_repository.list_enabled_daily_by_codes(
            self.market,
            scope.synchronization_codes,
        )

    def _refresh_instrument_names(self, symbols: list[Any]) -> None:
        """Refresh persisted names from remote instrument metadata in one routed batch."""
        fetch = getattr(self.market_data, "get_instrument_info", None)
        registry = getattr(self.market_data, "registry", None)
        if not symbols or not callable(fetch) or registry is None:
            return
        available = set(registry.names())
        providers = tuple(
            name
            for name in provider_order(self.market, INSTRUMENT_INFO)
            if name in REMOTE_INSTRUMENT_PROVIDERS and name in available
        )
        if not providers:
            return
        try:
            result = fetch([symbol.code for symbol in symbols], providers=providers)
        except Exception as exc:
            logger.warning("market=%s instrument name refresh failed: %s", self.market, exc)
            self.instrument_name_failures = {symbol.code: str(exc) for symbol in symbols}
            return
        by_code = {symbol.code: symbol for symbol in symbols}
        records = []
        for code, info in result.data.items():
            current = by_code.get(code)
            if current is None or not str(info.name or "").strip():
                continue
            records.append(
                {
                    "market": self.market,
                    "code": code,
                    "name": info.name,
                    "enabled": current.enabled,
                    "sync_daily": current.sync_daily,
                    "sync_minute": current.sync_minute,
                }
            )
        if records:
            self.symbol_repository.upsert_symbols(records, overwrite_runtime_flags=False)
        self.instrument_names_refreshed = len(records)
        self.instrument_name_failures = {
            **{code: "instrument name not found" for code in result.missing_symbols},
            **result.failed_symbols,
        }
        if result.missing_symbols or result.failed_symbols:
            logger.warning(
                "market=%s instrument name refresh partial refreshed=%s missing=%s failed=%s",
                self.market,
                len(records),
                len(result.missing_symbols),
                len(result.failed_symbols),
            )

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
            )
        except Exception as exc:
            logger.exception("market=%s code=%s daily fetch failed", self.market, symbol.code)
            return DailyResult("failed", reason=str(exc))
        return self._persist_daily_result(symbol, requested_days, routed)

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
                )
            except Exception as exc:
                logger.exception(
                    "market=%s data_type=daily batch fetch failed symbol_count=%s start_date=%s end_date=%s",
                    self.market,
                    len(codes),
                    start_date,
                    end_date,
                )
                routed = BatchBarResult(failed_symbols={code: str(exc) for code in codes})
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
                )
            except Exception as exc:
                logger.exception(
                    "market=%s data_type=daily automatic full refresh failed symbol_count=%s",
                    self.market,
                    len(codes),
                )
                routed = BatchBarResult(failed_symbols={code: str(exc) for code in codes})
            for symbol in automatic_full_symbols:
                result = self._persist_daily_result(symbol, full_days, routed, replace_history=True)
                result.automatic_full_refresh = True
                results[symbol.code] = result
        return results

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
            bars = routed.data.get(symbol.code, [])
            if not bars:
                failure = routed.failed_symbols.get(symbol.code)
                return DailyResult(
                    "failed",
                    reason="all daily providers failed",
                    fallback_reasons=[failure] if failure else [],
                )
            provider = routed.providers_used.get(symbol.code)
            if not provider:
                raise ValueError("daily provider attribution missing")
            returned_dates = {bar.trade_date for bar in bars}
            missing = sorted(set(requested_days).difference(returned_dates))
            if replace_history:
                coverage_ok, coverage_reason = self._validate_full_refresh_coverage(
                    symbol,
                    requested_days,
                    returned_dates,
                )
                if not coverage_ok:
                    logger.warning(
                        "market=%s code=%s full refresh rejected: %s",
                        self.market,
                        symbol.code,
                        coverage_reason,
                    )
                    return DailyResult(
                        status="partial",
                        providers=[provider],
                        missing_amount=any(bar.amount is None for bar in bars),
                        reason=coverage_reason,
                        fallback_reasons=(
                            [routed.failed_symbols[symbol.code]]
                            if symbol.code in routed.failed_symbols
                            else []
                        ),
                    )
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
                    }
                )
            if replace_history:
                stats = self.stock_repository.replace_daily_history(symbol.id, rows, provider)
            else:
                stats = self.stock_repository.upsert_daily(symbol.id, rows, provider)
            return DailyResult(
                status="partial" if missing else "success",
                inserted_rows=stats.inserted_rows,
                updated_rows=stats.updated_rows,
                deleted_rows=getattr(stats, "deleted_rows", 0),
                providers=[provider],
                missing_amount=any(bar.amount is None for bar in bars),
                reason=f"missing_trading_days={len(missing)}" if missing else "",
                fallback_reasons=[routed.failed_symbols[symbol.code]] if symbol.code in routed.failed_symbols else [],
            )
        except Exception as exc:
            logger.exception("market=%s code=%s daily persistence failed", self.market, symbol.code)
            return DailyResult("failed", reason=str(exc))

    def _validate_full_refresh_coverage(
        self,
        symbol: Any,
        requested_days: list[date],
        returned_dates: set[date],
    ) -> tuple[bool, str]:
        """Reject a full replacement when fetched history is materially incomplete."""
        expected_dates = set(requested_days)
        returned_expected = returned_dates.intersection(expected_dates)
        if not expected_dates or not returned_expected:
            return False, "full_refresh_coverage_insufficient returned=0 coverage=0.000 minimum=0.950"

        existing_dates = self.stock_repository.daily_dates(
            symbol.id,
            min(requested_days),
            max(requested_days),
        ).intersection(expected_dates)
        if existing_dates:
            existing_coverage = len(returned_expected.intersection(existing_dates)) / len(existing_dates)
            if existing_coverage >= FULL_REFRESH_MIN_COVERAGE:
                return True, ""
            return False, (
                "full_refresh_coverage_insufficient "
                f"returned={len(returned_expected)} expected={len(expected_dates)} "
                f"existing_dates={len(existing_dates)} existing_coverage={existing_coverage:.3f} "
                f"minimum={FULL_REFRESH_MIN_COVERAGE:.3f}"
            )

        returned_span = {
            day
            for day in expected_dates
            if min(returned_expected) <= day <= max(returned_expected)
        }
        continuity = len(returned_expected) / len(returned_span) if returned_span else 0.0
        if continuity >= FULL_REFRESH_MIN_COVERAGE:
            return True, ""
        return False, (
            "full_refresh_coverage_insufficient "
            f"returned={len(returned_expected)} expected={len(expected_dates)} "
            f"existing_dates=0 new_symbol=true continuity={continuity:.3f} "
            f"minimum={FULL_REFRESH_MIN_COVERAGE:.3f}"
        )

    def _summarize(
        self,
        results: list[SymbolResult],
        symbol_count: int,
    ) -> dict[str, Any]:
        statuses = {result.code: result.daily.status for result in results}
        fallback_reasons = [
            {"code": result.code, "reason": reason}
            for result in results
            for reason in result.daily.fallback_reasons
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
            "unsupported_symbol_count": len(self.unsupported_symbols),
            "unsupported_symbols": self.unsupported_symbols,
            "deleted_daily_rows": sum(result.daily.deleted_rows for result in results),
            "failure_count": len(failures),
            "failures": failures[:MAX_RESULT_ITEMS],
            "failures_truncated": len(failures) > MAX_RESULT_ITEMS,
        }


__all__ = [
    "MarketDataSyncError",
    "MarketDataSyncService",
]
