"""Unified market-scoped forward-adjusted daily OHLCV synchronization."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
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
        latest_completed_day = full_days[-1]
        retention_cutoff = latest_completed_day - timedelta(days=self.config.market_data_retention_daily_days - 1)
        symbol_ids = [symbol.id for symbol in symbols]
        deleted_daily_rows = int(self.stock_repository.delete_daily_before_symbols(symbol_ids, retention_cutoff) or 0)
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
            "retention_days=%s deleted_daily_rows=%s adjustment=forward",
            self.market,
            self.sync_mode,
            len(symbols),
            self.config.market_data_initial_daily_days,
            self.config.market_data_refresh_daily_days,
            self.config.market_data_retention_daily_days,
            deleted_daily_rows,
        )
        daily_results = self._sync_daily_batch_groups(symbols, daily_days_by_code)
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
            deleted_daily_rows=deleted_daily_rows,
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
                    "lot_size": info.lot_size,
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
                results[symbol.code] = self._persist_daily_result(
                    symbol,
                    daily_days_by_code[symbol.code],
                    routed,
                )
        return results

    def _persist_daily_result(
        self,
        symbol: Any,
        requested_days: list[date],
        routed: BatchBarResult,
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
            rows = []
            for bar in bars:
                vwap = bar.amount / bar.volume if bar.amount is not None and bar.amount > 0 and bar.volume > 0 else None
                rows.append(
                    {
                        "date": bar.trade_date,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "amount": bar.amount,
                        "vwap": vwap,
                        "vwap_source": provider if vwap is not None else None,
                        "vwap_quality": "calculated" if vwap is not None else "missing",
                    }
                )
            stats = self.stock_repository.upsert_daily(symbol.id, rows, provider)
            missing = sorted(set(requested_days).difference(bar.trade_date for bar in bars))
            return DailyResult(
                status="partial" if missing else "success",
                inserted_rows=stats.inserted_rows,
                updated_rows=stats.updated_rows,
                providers=[provider],
                missing_amount=any(bar.amount is None for bar in bars),
                vwap_qualities={
                    "calculated" if bar.amount is not None and bar.amount > 0 and bar.volume > 0 else "missing"
                    for bar in bars
                },
                reason=f"missing_trading_days={len(missing)}" if missing else "",
                fallback_reasons=[routed.failed_symbols[symbol.code]] if symbol.code in routed.failed_symbols else [],
            )
        except Exception as exc:
            logger.exception("market=%s code=%s daily persistence failed", self.market, symbol.code)
            return DailyResult("failed", reason=str(exc))

    def _summarize(
        self,
        results: list[SymbolResult],
        symbol_count: int,
        *,
        deleted_daily_rows: int = 0,
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
            "provider_vwap_symbols": sorted(
                result.code for result in results if "provider" in result.daily.vwap_qualities
            ),
            "calculated_vwap_symbols": sorted(
                result.code for result in results if "calculated" in result.daily.vwap_qualities
            ),
            "estimated_vwap_symbols": sorted(
                result.code for result in results if "estimated" in result.daily.vwap_qualities
            ),
            "missing_vwap_symbols": sorted(
                result.code for result in results if "missing" in result.daily.vwap_qualities
            ),
            "unsupported_symbol_count": len(self.unsupported_symbols),
            "unsupported_symbols": self.unsupported_symbols,
            "deleted_daily_rows": deleted_daily_rows,
            "failure_count": len(failures),
            "failures": failures[:MAX_RESULT_ITEMS],
            "failures_truncated": len(failures) > MAX_RESULT_ITEMS,
        }


__all__ = [
    "MarketDataSyncError",
    "MarketDataSyncService",
]
