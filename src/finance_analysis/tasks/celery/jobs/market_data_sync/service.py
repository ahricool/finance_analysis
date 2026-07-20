"""Unified market-scoped daily OHLCV and adjustment synchronization."""

from __future__ import annotations

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any

from finance_analysis.database.repositories.adjustment import StockAdjustmentRepository
from finance_analysis.database.repositories.stock import MarketDataSymbolRepository, StockRepository, UpsertStats
from finance_analysis.database.repositories.watch_list import WatchListRepo
from finance_analysis.integrations.market_data.config import DataProviderConfig, get_data_provider_config
from finance_analysis.market_review.trading_calendar import get_completed_trading_days, get_trading_days_between
from finance_analysis.stocks.markets import normalize_market_type
from finance_analysis.stocks.reference_data.stock_index import CSI300_STOCK_INDEX, SP500_STOCK_INDEX

from .models import AdjustmentResult, DailyResult, SymbolResult
from .provider_router import MarketDataProviderRouter

logger = logging.getLogger(__name__)
MAX_RESULT_ITEMS = 20


class MarketDataSyncError(RuntimeError):
    pass


class MarketDataSyncService:
    def __init__(
        self,
        market: str,
        *,
        symbol_repository: MarketDataSymbolRepository | None = None,
        stock_repository: StockRepository | None = None,
        adjustment_repository: StockAdjustmentRepository | None = None,
        watchlist_repository: WatchListRepo | None = None,
        router: MarketDataProviderRouter | None = None,
        config: DataProviderConfig | None = None,
        now: datetime | None = None,
    ):
        self.market = str(market).strip().upper()
        if self.market not in {"CN", "US"}:
            raise ValueError(f"Unsupported market={market}; market_data_sync currently supports CN or US")
        self.config = config or get_data_provider_config()
        self.symbol_repository = symbol_repository or MarketDataSymbolRepository()
        self.stock_repository = stock_repository or StockRepository()
        self.adjustment_repository = adjustment_repository or StockAdjustmentRepository()
        self.watchlist_repository = watchlist_repository or WatchListRepo()
        self.router = router or MarketDataProviderRouter(self.market, config=self.config)
        self.now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self.unsupported_symbols: list[dict[str, str]] = []

    def run(self) -> dict[str, Any]:
        symbols = self._load_scope()
        if not symbols:
            if self.unsupported_symbols:
                return self._summarize([], 0)
            raise MarketDataSyncError(f"No enabled daily symbols in the {self.market} synchronization scope")
        daily_days_by_code = {
            symbol.code: self._refresh_days(
                self.config.market_data_refresh_daily_days
                if self.stock_repository.has_daily_data(symbol.id)
                else self.config.market_data_initial_daily_days
            )
            for symbol in symbols
        }
        adjustment_days = self._refresh_days(self.config.market_data_retention_daily_days)
        retention_cutoff = adjustment_days[-1] - timedelta(
            days=self.config.market_data_retention_daily_days - 1
        )
        self.router.prepare_batches(symbols, daily_days_by_code, adjustment_days)
        logger.info(
            "market=%s job=market_data_sync symbol_count=%s initial_days=%s refresh_days=%s "
            "retention_days=%s adjustment_range=%s..%s",
            self.market,
            len(symbols),
            self.config.market_data_initial_daily_days,
            self.config.market_data_refresh_daily_days,
            self.config.market_data_retention_daily_days,
            adjustment_days[0],
            adjustment_days[-1],
        )
        workers = min(5, max(1, self.config.market_data_longbridge_max_concurrency)) if self.market == "US" else 1
        results: list[SymbolResult] = []
        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix=f"{self.market.lower()}-daily-sync",
        ) as executor:
            futures = {
                executor.submit(
                    self._sync_symbol,
                    symbol,
                    daily_days_by_code[symbol.code],
                    adjustment_days,
                    retention_cutoff,
                ): symbol
                for symbol in symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    logger.exception("market=%s code=%s synchronization failed", self.market, symbol.code)
                    results.append(
                        SymbolResult(
                            symbol.code,
                            DailyResult("failed", reason=str(exc)),
                            AdjustmentResult("failed", reason=str(exc)),
                        )
                    )
        summary = self._summarize(results, len(symbols))
        if summary["success_symbols"] + summary["partial_symbols"] == 0:
            raise MarketDataSyncError(f"All {len(symbols)} {self.market} symbols failed; see task log")
        return summary

    def _load_scope(self) -> list[Any]:
        reference = SP500_STOCK_INDEX if self.market == "US" else CSI300_STOCK_INDEX if self.market == "CN" else {}
        reference_codes = {
            f"{ticker}.US" if self.market == "US" else ticker
            for ticker in reference
        }
        watch_records: list[dict[str, Any]] = []
        unsupported: dict[tuple[str, str], dict[str, str]] = {}
        for item in self.watchlist_repository.list_all():
            try:
                item_market = normalize_market_type(item.market_type, item.code)
                if item_market == "HK":
                    if self.market == "CN":
                        try:
                            unsupported_code = self._canonical_watch_code(item.code, "HK")
                        except ValueError:
                            unsupported_code = str(item.code or "").strip().upper()
                        unsupported[(unsupported_code, "HK")] = {
                            "code": unsupported_code,
                            "market": "HK",
                            "reason": "HK daily synchronization is temporarily unsupported",
                        }
                    continue
                if item_market != self.market:
                    continue
                code = self._canonical_watch_code(item.code, self.market)
            except ValueError as exc:
                logger.warning("market=%s watchlist_code=%s skipped reason=%s", self.market, item.code, exc)
                continue
            reference_codes.add(code)
            watch_records.append(
                {
                    "market": self.market,
                    "code": code,
                    "name": item.name or code,
                }
            )
        self.unsupported_symbols = sorted(unsupported.values(), key=lambda item: item["code"])
        if watch_records:
            self.symbol_repository.upsert_symbols(watch_records, overwrite_runtime_flags=False)
        return self.symbol_repository.list_enabled_daily_by_codes(self.market, reference_codes)

    @staticmethod
    def _canonical_watch_code(code: str, market: str) -> str:
        text = str(code or "").strip().upper()
        if market == "US":
            base = text[:-3] if text.endswith(".US") else text
            if not base:
                raise ValueError("empty US ticker")
            return f"{base}.US"
        if market == "HK":
            base = text.removeprefix("HK")
            if base.endswith(".HK"):
                base = base[:-3]
            if not base.isdigit() or int(base) <= 0:
                raise ValueError("invalid HK ticker")
            return f"{int(base)}.HK"
        base = text.removeprefix("SH").removeprefix("SZ")
        suffix = ""
        if base.endswith((".SH", ".SS", ".SZ")):
            suffix = base[-3:]
            base = base[:-3]
        if not base.isdigit() or len(base) != 6:
            raise ValueError("invalid CN ticker")
        if suffix in (".SH", ".SS"):
            exchange = ".SH"
        elif suffix == ".SZ":
            exchange = ".SZ"
        elif base.startswith(("5", "6", "9")):
            exchange = ".SH"
        else:
            exchange = ".SZ"
        return f"{base}{exchange}"

    def _refresh_days(self, natural_days: int) -> list[date]:
        end = get_completed_trading_days(self.market.lower(), 1, self.now)[-1]
        start = end - timedelta(days=natural_days - 1)
        return get_trading_days_between(self.market.lower(), start, end)

    def _sync_symbol(
        self,
        symbol: Any,
        daily_days: list[date],
        adjustment_days: list[date],
        retention_cutoff: date,
    ) -> SymbolResult:
        daily = self._sync_daily(symbol, daily_days)
        adjustment = self._sync_adjustment(symbol, adjustment_days)
        if daily.status == "success":
            daily.deleted_rows = int(self.stock_repository.delete_daily_before(symbol.id, retention_cutoff) or 0)
            if adjustment.status == "success":
                adjustment.deleted_rows = int(
                    self.adjustment_repository.delete_before(symbol.id, retention_cutoff) or 0
                )
        return SymbolResult(symbol.code, daily, adjustment)

    def _sync_daily(self, symbol: Any, requested_days: list[date]) -> DailyResult:
        try:
            routed = self.router.fetch_daily(symbol, requested_days)
            if not routed.batches:
                return DailyResult(
                    "failed",
                    reason="all daily providers failed",
                    fallback_reasons=routed.fallback_reasons,
                )
            stats = UpsertStats()
            missing_amount = False
            vwap_qualities: set[str] = set()
            for batch in routed.batches:
                missing_amount = missing_amount or any(row.get("amount") is None for row in batch.rows)
                vwap_qualities.update(str(row.get("vwap_quality") or "missing") for row in batch.rows)
                current = self.stock_repository.upsert_daily(
                    symbol.id,
                    batch.rows,
                    batch.provider,
                    batch.priority,
                )
                stats = UpsertStats(
                    stats.inserted_rows + current.inserted_rows,
                    stats.updated_rows + current.updated_rows,
                    stats.skipped_lower_priority_rows + current.skipped_lower_priority_rows,
                )
            return DailyResult(
                status="partial" if routed.missing else "success",
                inserted_rows=stats.inserted_rows,
                updated_rows=stats.updated_rows,
                skipped_lower_priority_rows=stats.skipped_lower_priority_rows,
                providers=routed.providers_used,
                missing_amount=missing_amount,
                vwap_qualities=vwap_qualities,
                reason=f"missing_trading_days={len(routed.missing)}" if routed.missing else "",
                fallback_reasons=routed.fallback_reasons,
            )
        except Exception as exc:
            logger.exception("market=%s code=%s daily sync failed", self.market, symbol.code)
            return DailyResult("failed", reason=str(exc))

    def _sync_adjustment(self, symbol: Any, requested_days: list[date]) -> AdjustmentResult:
        routed = self.router.fetch_adjustment(symbol, requested_days)
        if routed.provider is None or routed.data is None:
            return AdjustmentResult(
                "failed",
                reason="no adjustment provider succeeded",
                fallback_reasons=routed.fallback_reasons,
            )
        if not routed.data.adjustment_factors:
            return AdjustmentResult(
                "failed",
                provider=routed.provider,
                reason="provider returned no daily adjustment factors",
                fallback_reasons=routed.fallback_reasons,
            )
        start_date, end_date = min(requested_days), max(requested_days)
        factors_by_date = {
            row["trade_date"]: row for row in routed.data.adjustment_factors
        }
        factor_rows = list(factors_by_date.values())
        action_rows = list(
            {
                (row["action_date"], row["action_type"]): row
                for row in routed.data.corporate_actions
            }.values()
        )
        action_changed = self.adjustment_repository.has_corporate_action_changes(
            symbol.id,
            start_date,
            end_date,
            action_rows,
            routed.provider,
            complete=routed.data.corporate_actions_complete,
        )
        if routed.data.corporate_actions_complete:
            action_stats = self.adjustment_repository.replace_corporate_actions(
                symbol.id,
                start_date,
                end_date,
                action_rows,
                routed.provider,
            )
        else:
            action_stats = self.adjustment_repository.upsert_corporate_actions(
                symbol.id,
                start_date,
                end_date,
                action_rows,
                routed.provider,
            )

        factor_dates = {row["trade_date"] for row in factor_rows}
        complete_factor_window = (
            routed.data.adjustment_factors_complete
            and set(requested_days).issubset(factor_dates)
        )
        if action_changed and complete_factor_window:
            factor_stats = self.adjustment_repository.replace_adjustment_factors(
                symbol.id,
                start_date,
                end_date,
                factor_rows,
                routed.provider,
            )
        else:
            refresh_cutoff = end_date - timedelta(days=self.config.market_data_refresh_daily_days - 1)
            rows_to_upsert = factor_rows if action_changed else [
                row for row in factor_rows if row["trade_date"] >= refresh_cutoff
            ]
            factor_stats = self.adjustment_repository.upsert_adjustment_factors(
                symbol.id,
                start_date,
                end_date,
                rows_to_upsert,
                routed.provider,
            )
        return AdjustmentResult(
            "success",
            changed=factor_stats.changed or action_stats.changed,
            corporate_action_rows=len(action_rows),
            adjustment_factor_rows=len(factor_rows),
            provider=routed.provider,
            fallback_reasons=routed.fallback_reasons,
        )

    def _summarize(self, results: list[SymbolResult], symbol_count: int) -> dict[str, Any]:
        statuses: dict[str, str] = {}
        for result in results:
            if result.daily.status == "failed":
                statuses[result.code] = "failed"
            elif result.daily.status == "partial" or result.adjustment.status == "failed":
                statuses[result.code] = "partial"
            else:
                statuses[result.code] = "success"
        fallback_reasons = [
            {"code": result.code, "reason": reason}
            for result in results
            for reason in [*result.daily.fallback_reasons, *result.adjustment.fallback_reasons]
        ]
        failures = [
            {
                "code": result.code,
                "daily_reason": result.daily.reason,
                "adjustment_reason": result.adjustment.reason,
            }
            for result in results
            if statuses[result.code] != "success"
        ]
        provider_counts = Counter(
            provider
            for result in results
            for provider in result.daily.providers
        )
        return {
            "sync_status": "partial" if failures else "success",
            "market": self.market,
            "symbol_count": symbol_count,
            "success_symbols": sum(status == "success" for status in statuses.values()),
            "partial_symbols": sum(status == "partial" for status in statuses.values()),
            "failed_symbols": sum(status == "failed" for status in statuses.values()),
            "inserted_rows": sum(result.daily.inserted_rows for result in results),
            "updated_rows": sum(result.daily.updated_rows for result in results),
            "provider_counts": dict(provider_counts),
            "missing_amount_symbols": sorted(
                result.code for result in results if result.daily.missing_amount
            ),
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
            "adjustment_changed_symbols": sorted(
                result.code for result in results if result.adjustment.changed
            ),
            "corporate_action_rows": sum(result.adjustment.corporate_action_rows for result in results),
            "adjustment_factor_rows": sum(result.adjustment.adjustment_factor_rows for result in results),
            "deleted_daily_rows": sum(result.daily.deleted_rows for result in results),
            "deleted_adjustment_rows": sum(result.adjustment.deleted_rows for result in results),
            "failure_count": len(failures),
            "failures": failures[:MAX_RESULT_ITEMS],
            "failures_truncated": len(failures) > MAX_RESULT_ITEMS,
        }


__all__ = [
    "MarketDataSyncError",
    "MarketDataSyncService",
]
