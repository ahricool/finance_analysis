"""Unified market-scoped daily OHLCV and adjustment synchronization."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from finance_analysis.database.repositories.adjustment import StockAdjustmentRepository
from finance_analysis.database.repositories.stock import MarketDataSymbolRepository, StockRepository
from finance_analysis.integrations.market_data.config import (
    DataProviderConfig,
    get_data_provider_config,
    provider_order,
)
from finance_analysis.integrations.market_data.models import AdjustmentResult as MarketAdjustmentResult
from finance_analysis.integrations.market_data.models import BatchBarResult
from finance_analysis.integrations.market_data.registry import INSTRUMENT_INFO
from finance_analysis.integrations.market_data.service import MarketDataService
from finance_analysis.market_review.trading_calendar import get_completed_trading_days, get_trading_days_between
from finance_analysis.stocks.market_scope import MarketDataScopeResolver

from .models import AdjustmentResult, DailyResult, SymbolResult, normalize_sync_mode

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
        adjustment_repository: StockAdjustmentRepository | None = None,
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
        self.adjustment_repository = adjustment_repository or StockAdjustmentRepository()
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
        full_adjustment_days = self._refresh_days(self.config.market_data_initial_daily_days)
        latest_completed_day = full_adjustment_days[-1]
        retention_cutoff = latest_completed_day - timedelta(days=self.config.market_data_retention_daily_days - 1)
        symbol_ids = [symbol.id for symbol in symbols]
        deleted_daily_rows = int(self.stock_repository.delete_daily_before_symbols(symbol_ids, retention_cutoff) or 0)
        deleted_adjustment_rows = int(
            self.adjustment_repository.delete_before_symbols(symbol_ids, retention_cutoff) or 0
        )
        factor_gaps_before = self._missing_factor_gaps(symbol_ids, retention_cutoff, latest_completed_day)
        repair_symbol_ids = set(factor_gaps_before)
        daily_days_by_code: dict[str, list[date]] = {}
        adjustment_days_by_code: dict[str, list[date]] = {}
        force_full_factor_window_by_code: dict[str, bool] = {}
        for symbol in symbols:
            has_history = self.stock_repository.has_daily_data(symbol.id) if self.sync_mode == "incremental" else False
            natural_days = (
                self.config.market_data_refresh_daily_days
                if self.sync_mode == "incremental" and has_history
                else self.config.market_data_initial_daily_days
            )
            daily_days_by_code[symbol.code] = self._refresh_days(natural_days)
            force_full_factor_window = not has_history or symbol.id in repair_symbol_ids
            adjustment_days_by_code[symbol.code] = (
                list(full_adjustment_days) if force_full_factor_window else list(daily_days_by_code[symbol.code])
            )
            force_full_factor_window_by_code[symbol.code] = force_full_factor_window
        logger.info(
            "market=%s job=market_data_sync sync_mode=%s symbol_count=%s initial_days=%s refresh_days=%s "
            "retention_days=%s factor_repair_symbols=%s deleted_daily_rows=%s deleted_adjustment_rows=%s",
            self.market,
            self.sync_mode,
            len(symbols),
            self.config.market_data_initial_daily_days,
            self.config.market_data_refresh_daily_days,
            self.config.market_data_retention_daily_days,
            len(repair_symbol_ids),
            deleted_daily_rows,
            deleted_adjustment_rows,
        )
        daily_results = self._sync_daily_batch_groups(symbols, daily_days_by_code)
        if self.market == "US":
            adjustment_results = self._sync_adjustment_batch_groups(
                symbols,
                adjustment_days_by_code,
                full_adjustment_days,
                force_full_factor_window_by_code,
            )
        else:
            adjustment_results = {}
            for symbol in symbols:
                try:
                    adjustment_results[symbol.code] = self._sync_adjustment(
                        symbol,
                        adjustment_days_by_code[symbol.code],
                        full_adjustment_days,
                        force_full_factor_window=force_full_factor_window_by_code[symbol.code],
                    )
                except Exception as exc:
                    logger.exception("market=%s code=%s adjustment synchronization failed", self.market, symbol.code)
                    adjustment_results[symbol.code] = AdjustmentResult("failed", reason=str(exc))
        results = [
            SymbolResult(
                symbol.code,
                daily_results.get(symbol.code, DailyResult("failed", reason="daily result missing")),
                adjustment_results.get(
                    symbol.code,
                    AdjustmentResult("failed", reason="adjustment result missing"),
                ),
            )
            for symbol in symbols
        ]
        factor_gaps_after = self._missing_factor_gaps(symbol_ids, retention_cutoff, latest_completed_day)
        self._apply_unresolved_factor_gaps(results, symbols, factor_gaps_after)
        summary = self._summarize(
            results,
            len(symbols),
            deleted_daily_rows=deleted_daily_rows,
            deleted_adjustment_rows=deleted_adjustment_rows,
        )
        codes_by_id = {symbol.id: symbol.code for symbol in symbols}
        summary.update(
            {
                "factor_repair_symbols": len(repair_symbol_ids),
                "factor_repair_codes": sorted(codes_by_id[symbol_id] for symbol_id in repair_symbol_ids),
                "missing_factor_rows_before": self._missing_factor_row_count(factor_gaps_before),
                "missing_factor_rows_after": self._missing_factor_row_count(factor_gaps_after),
                "unresolved_factor_gaps": self._serialize_factor_gaps(symbols, factor_gaps_after)[:MAX_RESULT_ITEMS],
                "unresolved_factor_gaps_truncated": len(factor_gaps_after) > MAX_RESULT_ITEMS,
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

    def _missing_factor_gaps(
        self,
        symbol_ids: list[int],
        start_date: date,
        end_date: date,
    ) -> dict[int, dict[str, Any]]:
        return dict(
            self.adjustment_repository.missing_adjustment_factor_gaps(
                symbol_ids,
                start_date,
                end_date,
            )
        )

    @staticmethod
    def _missing_factor_row_count(gaps: dict[int, dict[str, Any]]) -> int:
        return sum(int(gap["missing_rows"]) for gap in gaps.values())

    @staticmethod
    def _serialize_factor_gaps(
        symbols: list[Any],
        gaps: dict[int, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        codes_by_id = {symbol.id: symbol.code for symbol in symbols}
        return [
            {
                "code": codes_by_id[symbol_id],
                "first_missing_date": str(gap["first_missing_date"]),
                "last_missing_date": str(gap["last_missing_date"]),
                "missing_rows": int(gap["missing_rows"]),
            }
            for symbol_id, gap in sorted(gaps.items(), key=lambda item: codes_by_id[item[0]])
        ]

    def _apply_unresolved_factor_gaps(
        self,
        results: list[SymbolResult],
        symbols: list[Any],
        gaps: dict[int, dict[str, Any]],
    ) -> None:
        gaps_by_code = {symbol.code: gaps[symbol.id] for symbol in symbols if symbol.id in gaps}
        for result in results:
            gap = gaps_by_code.get(result.code)
            if gap is None:
                continue
            reason = (
                f"unresolved adjustment factor gaps: missing_rows={int(gap['missing_rows'])}, "
                f"range={gap['first_missing_date']}..{gap['last_missing_date']}"
            )
            if result.adjustment.status == "success":
                result.adjustment.status = "partial"
            if reason not in result.adjustment.reason:
                result.adjustment.reason = "; ".join(filter(None, [result.adjustment.reason, reason]))
            if reason not in result.adjustment.fallback_reasons:
                result.adjustment.fallback_reasons.append(reason)

    def _sync_daily(self, symbol: Any, requested_days: list[date]) -> DailyResult:
        try:
            routed = self.market_data.get_daily_bars(
                [symbol.code],
                min(requested_days),
                max(requested_days),
                adjustment="raw",
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
                    adjustment="raw",
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

    def _sync_adjustment(
        self,
        symbol: Any,
        requested_days: list[date],
        full_adjustment_days: list[date] | None = None,
        *,
        force_full_factor_window: bool = False,
        routed: MarketAdjustmentResult | None = None,
    ) -> AdjustmentResult:
        if routed is None:
            routed = self.market_data.get_adjustment_factors(
                [symbol.code], min(requested_days), max(requested_days)
            )
        provider = routed.providers_used.get(symbol.code)
        factors = routed.factors.get(symbol.code, [])
        if provider is None or not factors:
            failure = routed.failed_symbols.get(symbol.code)
            return AdjustmentResult(
                "failed",
                reason="no adjustment provider succeeded",
                fallback_reasons=[failure] if failure else [],
            )
        start_date, end_date = min(requested_days), max(requested_days)
        factors_by_date = {
            item.trade_date: {
                "trade_date": item.trade_date,
                "forward_adjustment_factor": item.factor,
                "hfq_factor": None,
                "hfq_cash": None,
                "adj_close": None,
            }
            for item in factors
            if start_date <= item.trade_date <= end_date
        }
        factor_rows = list(factors_by_date.values())
        if not factor_rows:
            failure = routed.failed_symbols.get(symbol.code)
            return AdjustmentResult(
                "failed",
                provider=provider,
                reason="provider returned no in-window daily adjustment factors",
                fallback_reasons=[failure] if failure else [],
            )
        replace_full_factor_window = force_full_factor_window
        is_recent_probe = bool(full_adjustment_days and requested_days != full_adjustment_days)
        if is_recent_probe and self.adjustment_repository.has_adjustment_factor_changes(
            symbol.id,
            start_date,
            end_date,
            factor_rows,
        ):
            logger.info(
                "market=%s code=%s adjustment factors changed in recent window; refreshing five years",
                self.market,
                symbol.code,
            )
            full_routed = self.market_data.get_adjustment_factors(
                [symbol.code], min(full_adjustment_days), max(full_adjustment_days)
            )
            fallback_reasons = [
                reason
                for reason in (
                    routed.failed_symbols.get(symbol.code),
                    full_routed.failed_symbols.get(symbol.code),
                )
                if reason
            ]
            full_provider = full_routed.providers_used.get(symbol.code)
            full_factors = full_routed.factors.get(symbol.code, [])
            if full_provider is None or not full_factors:
                return AdjustmentResult(
                    "failed",
                    reason="adjustment factor changed but five-year refresh failed",
                    fallback_reasons=fallback_reasons,
                )
            routed = full_routed
            provider = full_provider
            factors = full_factors
            requested_days = full_adjustment_days
            start_date, end_date = min(requested_days), max(requested_days)
            factors_by_date = {
                item.trade_date: {
                    "trade_date": item.trade_date,
                    "forward_adjustment_factor": item.factor,
                    "hfq_factor": None,
                    "hfq_cash": None,
                    "adj_close": None,
                }
                for item in factors
                if start_date <= item.trade_date <= end_date
            }
            factor_rows = list(factors_by_date.values())
            if not factor_rows:
                return AdjustmentResult(
                    "failed",
                    provider=provider,
                    reason="five-year refresh returned no in-window daily adjustment factors",
                    fallback_reasons=fallback_reasons,
                )
            replace_full_factor_window = True
        action_rows = []
        for item in routed.corporate_actions.get(symbol.code, []):
            row = {
                "action_date": item.action_date,
                "action_type": item.action_type,
                "cash_dividend": item.value if item.action_type == "dividend" else None,
                "split_ratio": item.value if item.action_type == "split" else None,
                "bonus_ratio": item.value if item.action_type == "bonus" else None,
                "rights_ratio": item.value if item.action_type == "rights" else None,
                "rights_price": None,
                "currency": None,
                "raw_payload": {"value": item.value},
            }
            if start_date <= item.action_date <= end_date:
                action_rows.append(row)
        action_stats = self.adjustment_repository.replace_corporate_actions(
            symbol.id, start_date, end_date, action_rows, provider
        )

        factor_dates = {row["trade_date"] for row in factor_rows}
        expected_factor_dates = (
            self.stock_repository.daily_dates(symbol.id, start_date, end_date) if replace_full_factor_window else set()
        )
        complete_factor_window = expected_factor_dates.issubset(factor_dates)
        adjustment_status = "success"
        adjustment_reason = ""
        if replace_full_factor_window and complete_factor_window:
            factor_stats = self.adjustment_repository.replace_adjustment_factors(
                symbol.id,
                start_date,
                end_date,
                factor_rows,
                provider,
            )
        else:
            if replace_full_factor_window:
                adjustment_status = "partial"
                adjustment_reason = "incomplete five-year factor refresh; preserved stored rows outside response"
                logger.warning(
                    "market=%s code=%s provider=%s data_type=adjustment reason=%s",
                    self.market,
                    symbol.code,
                    provider,
                    adjustment_reason,
                )
            factor_stats = self.adjustment_repository.upsert_adjustment_factors(
                symbol.id,
                start_date,
                end_date,
                factor_rows,
                provider,
            )
        return AdjustmentResult(
            adjustment_status,
            changed=factor_stats.changed or action_stats.changed,
            corporate_action_rows=len(action_rows),
            adjustment_factor_rows=len(factor_rows),
            provider=provider,
            reason=adjustment_reason,
            fallback_reasons=[routed.failed_symbols[symbol.code]] if symbol.code in routed.failed_symbols else [],
        )

    def _sync_adjustment_batch_groups(
        self,
        symbols: list[Any],
        adjustment_days_by_code: dict[str, list[date]],
        full_adjustment_days: list[date],
        force_full_factor_window_by_code: dict[str, bool],
    ) -> dict[str, AdjustmentResult]:
        groups: dict[tuple[date, date], list[Any]] = defaultdict(list)
        for symbol in symbols:
            requested_days = adjustment_days_by_code[symbol.code]
            groups[(min(requested_days), max(requested_days))].append(symbol)
        logger.info(
            "market=%s data_type=adjustment symbol_count=%s batch_group_count=%s",
            self.market,
            len(symbols),
            len(groups),
        )

        results: dict[str, AdjustmentResult] = {}
        for (start_date, end_date), grouped_symbols in groups.items():
            codes = [symbol.code for symbol in grouped_symbols]
            logger.info(
                "market=%s data_type=adjustment action=batch_fetch symbol_count=%s "
                "start_date=%s end_date=%s sample=%s",
                self.market,
                len(codes),
                start_date,
                end_date,
                codes[:5],
            )
            try:
                routed = self.market_data.get_adjustment_factors(codes, start_date, end_date)
            except Exception as exc:
                logger.exception(
                    "market=%s data_type=adjustment batch fetch failed symbol_count=%s "
                    "start_date=%s end_date=%s",
                    self.market,
                    len(codes),
                    start_date,
                    end_date,
                )
                routed = MarketAdjustmentResult(failed_symbols={code: str(exc) for code in codes})
            for symbol in grouped_symbols:
                try:
                    results[symbol.code] = self._sync_adjustment(
                        symbol,
                        adjustment_days_by_code[symbol.code],
                        full_adjustment_days,
                        force_full_factor_window=force_full_factor_window_by_code[symbol.code],
                        routed=routed,
                    )
                except Exception as exc:
                    logger.exception(
                        "market=%s code=%s adjustment persistence failed",
                        self.market,
                        symbol.code,
                    )
                    results[symbol.code] = AdjustmentResult("failed", reason=str(exc))
        return results

    def _summarize(
        self,
        results: list[SymbolResult],
        symbol_count: int,
        *,
        deleted_daily_rows: int = 0,
        deleted_adjustment_rows: int = 0,
    ) -> dict[str, Any]:
        statuses: dict[str, str] = {}
        for result in results:
            if result.daily.status == "failed":
                statuses[result.code] = "failed"
            elif result.daily.status == "partial" or result.adjustment.status in {"partial", "failed"}:
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
            "adjustment_changed_symbols": sorted(result.code for result in results if result.adjustment.changed),
            "corporate_action_rows": sum(result.adjustment.corporate_action_rows for result in results),
            "adjustment_factor_rows": sum(result.adjustment.adjustment_factor_rows for result in results),
            "deleted_daily_rows": deleted_daily_rows,
            "deleted_adjustment_rows": deleted_adjustment_rows,
            "factor_repair_symbols": 0,
            "factor_repair_codes": [],
            "missing_factor_rows_before": 0,
            "missing_factor_rows_after": 0,
            "unresolved_factor_gaps": [],
            "unresolved_factor_gaps_truncated": False,
            "failure_count": len(failures),
            "failures": failures[:MAX_RESULT_ITEMS],
            "failures_truncated": len(failures) > MAX_RESULT_ITEMS,
        }


__all__ = [
    "MarketDataSyncError",
    "MarketDataSyncService",
]
