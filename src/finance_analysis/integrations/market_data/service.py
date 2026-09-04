"""The only market-data entry point used by business code."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime
from typing import Any, Iterable, Literal

import pandas as pd

from finance_analysis.database.repositories.stock import InstrumentRepository, StockRepository
from finance_analysis.market_review.trading_calendar import get_trading_days_between

from .config import DataProviderConfig, get_data_provider_config
from .errors import MarketDataIncompleteError
from .models import (
    Adjustment,
    BatchBarResult,
    BatchInstrumentResult,
    BatchQuoteResult,
    DailyBarsRequest,
    InstrumentInfo,
    InstrumentRequest,
    Market,
    MarketBar,
    MarketIndex,
    MarketStats,
    MinuteBarsRequest,
    QuoteRequest,
    SectorRankings,
    adjustment_from_value,
    market_from_value,
)
from .normalizer import bars_from_frame, canonical_symbol, currency_for_market, infer_market, quote_from_value
from .registry import (
    DAILY_BARS,
    INSTRUMENT_INFO,
    LATEST_MARKET_SNAPSHOT,
    MARKET_INDICES,
    MARKET_STATS,
    MINUTE_BARS,
    REALTIME_QUOTES,
    SECTOR_RANKINGS,
    ProviderRegistry,
)
from .router import MarketDataRouter

logger = logging.getLogger(__name__)


class _DatabaseInstrumentProvider:
    name = "database"

    def __init__(self, repository: InstrumentRepository | None = None) -> None:
        self.repository = repository

    def get_instrument_info(self, request: InstrumentRequest) -> BatchInstrumentResult:
        if self.repository is None:
            try:
                self.repository = InstrumentRepository()
            except Exception as exc:
                return BatchInstrumentResult(failed_symbols={symbol: str(exc) for symbol in request.symbols})
        result = BatchInstrumentResult()
        for value in request.symbols:
            symbol = canonical_symbol(value)
            try:
                row = self.repository.get_by_code(symbol)
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
                continue
            if row is None or not str(row.name or "").strip():
                result.missing_symbols.append(symbol)
                continue
            market = infer_market(symbol)
            result.data[symbol] = InstrumentInfo(
                symbol=symbol,
                market=market,
                name=str(row.name).strip(),
                provider=self.name,
                currency=currency_for_market(market),
                exchange=symbol.rsplit(".", 1)[1],
                instrument_type=str(row.instrument_type).lower(),
            )
            result.providers_used[symbol] = self.name
        return result


class _StreamingStateProvider:
    name = "streaming"

    def __init__(self, source: Any = None) -> None:
        self._source = source

    def _get_source(self):
        if self._source is None:
            from .realtime_state.data_source import get_default_sync_realtime_source

            self._source = get_default_sync_realtime_source()
        return self._source

    def fetch_quotes(self, request: QuoteRequest) -> BatchQuoteResult:
        source = self._get_source()
        result = BatchQuoteResult()
        for value in request.symbols:
            symbol = canonical_symbol(value)
            try:
                raw = source.get_quote(symbol, market_type=infer_market(symbol).value)
                quote = quote_from_value(raw.to_dict() if raw is not None else None, symbol=symbol, provider=self.name)
                if quote is None:
                    result.missing_symbols.append(symbol)
                else:
                    result.data[symbol] = quote
                    result.providers_used[symbol] = self.name
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
        return result

    def fetch_minute_bars(self, request: MinuteBarsRequest) -> BatchBarResult:
        source = self._get_source()
        result = BatchBarResult()
        minutes = max(1, int((request.end_time - request.start_time).total_seconds() // 60) + 5)
        for value in request.symbols:
            symbol = canonical_symbol(value)
            try:
                rows = source.get_recent_bars(
                    symbol,
                    minutes,
                    market_type=infer_market(symbol).value,
                    minimum_count=1,
                    include_incomplete=False,
                    now=request.end_time,
                )
                bars = bars_from_frame(
                    pd.DataFrame(rows or []).rename(columns={"timestamp": "bar_time", "turnover": "amount"}),
                    symbol=symbol,
                    provider=self.name,
                    interval=request.interval,
                )
                bars = [
                    bar
                    for bar in bars
                    if bar.bar_time is not None and request.start_time <= bar.bar_time < request.end_time
                ]
                if bars:
                    result.data[symbol] = bars
                    result.providers_used[symbol] = self.name
                else:
                    result.missing_symbols.append(symbol)
            except Exception as exc:
                result.failed_symbols[symbol] = str(exc)
        return result


def build_default_registry(
    config: DataProviderConfig | None = None,
    *,
    instrument_repository: InstrumentRepository | None = None,
    streaming_source: Any = None,
) -> ProviderRegistry:
    from .providers.akshare import AkShareProvider
    from .providers.baostock import BaoStockProvider
    from .providers.efinance import EfinanceProvider
    from .providers.pytdx import PyTDXProvider
    from .providers.tickflow import TickFlowFreeProvider
    from .providers.yfinance import YFinanceProvider

    resolved_config = config or get_data_provider_config()
    registry = ProviderRegistry()
    registry.register("database", _DatabaseInstrumentProvider(instrument_repository), capabilities={INSTRUMENT_INFO})
    registry.register(
        "streaming",
        _StreamingStateProvider(streaming_source),
        capabilities={MINUTE_BARS, REALTIME_QUOTES},
    )
    registry.register(
        "tickflow",
        TickFlowFreeProvider(
            batch_size=resolved_config.market_data_tickflow_batch_size,
            max_workers=resolved_config.market_data_tickflow_max_concurrency,
        ),
        capabilities={DAILY_BARS, INSTRUMENT_INFO},
    )
    registry.register(
        "akshare",
        AkShareProvider(),
        capabilities={
            DAILY_BARS,
            MINUTE_BARS,
            REALTIME_QUOTES,
            LATEST_MARKET_SNAPSHOT,
            MARKET_INDICES,
            MARKET_STATS,
            SECTOR_RANKINGS,
            INSTRUMENT_INFO,
        },
    )
    registry.register(
        "pytdx",
        PyTDXProvider(),
        capabilities={
            DAILY_BARS,
            MINUTE_BARS,
            REALTIME_QUOTES,
            LATEST_MARKET_SNAPSHOT,
            MARKET_INDICES,
            INSTRUMENT_INFO,
        },
    )
    registry.register("baostock", BaoStockProvider(), capabilities={DAILY_BARS, INSTRUMENT_INFO})
    registry.register(
        "efinance",
        EfinanceProvider(),
        capabilities={
            MINUTE_BARS,
            REALTIME_QUOTES,
            LATEST_MARKET_SNAPSHOT,
            MARKET_INDICES,
            MARKET_STATS,
            SECTOR_RANKINGS,
            INSTRUMENT_INFO,
        },
    )
    registry.register(
        "yfinance",
        YFinanceProvider(
            batch_size=resolved_config.market_data_yfinance_batch_size,
            max_workers=resolved_config.market_data_yfinance_max_concurrency,
            max_retries=resolved_config.market_data_yfinance_max_retries,
        ),
        capabilities={DAILY_BARS, MINUTE_BARS, REALTIME_QUOTES, MARKET_INDICES, INSTRUMENT_INFO},
    )
    if resolved_config.longbridge_configured:
        from .providers.longbridge.market import LongbridgeProvider

        registry.register(
            "longbridge",
            LongbridgeProvider(),
            capabilities={DAILY_BARS, MINUTE_BARS, REALTIME_QUOTES, MARKET_INDICES, INSTRUMENT_INFO},
        )
    return registry


class MarketDataService:
    def __init__(
        self,
        registry: ProviderRegistry | None = None,
        *,
        config: DataProviderConfig | None = None,
        instrument_repository: InstrumentRepository | None = None,
        stock_repository: StockRepository | None = None,
        streaming_source: Any = None,
    ) -> None:
        self.config = config or get_data_provider_config()
        self.registry = registry or build_default_registry(
            self.config,
            instrument_repository=instrument_repository,
            streaming_source=streaming_source,
        )
        self.router = MarketDataRouter(self.registry)
        self.instrument_repository = instrument_repository
        self.stock_repository = stock_repository

    @staticmethod
    def _canonical_symbols(symbols: Iterable[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(canonical_symbol(symbol) for symbol in symbols))

    def get_daily_bars(
        self,
        symbols: Iterable[str],
        start_date: date,
        end_date: date,
        *,
        adjustment: Adjustment | str,
        providers: Iterable[str] | None = None,
        source_policy: Literal["db_only", "db_first", "remote_only"] = "db_first",
        persist: bool = True,
    ) -> BatchBarResult:
        canonical = self._canonical_symbols(symbols)
        requested_adjustment = adjustment_from_value(adjustment)
        if requested_adjustment is not Adjustment.FORWARD:
            raise ValueError("Daily bars are stored and served only as forward-adjusted prices")
        if source_policy not in {"db_only", "db_first", "remote_only"}:
            raise ValueError("source_policy must be db_only, db_first, or remote_only")
        request = DailyBarsRequest(canonical, start_date, end_date, Adjustment.FORWARD)
        if source_policy == "remote_only":
            remote = self.router.route_daily(request, providers)
            if persist:
                self._persist_remote_daily(remote)
            return remote
        try:
            persisted, missing = self._load_persisted_daily(request)
        except Exception:
            if source_policy == "db_only":
                raise
            remote = self.router.route_daily(request, providers)
            self._persist_remote_daily(remote)
            return remote
        if not missing:
            return persisted
        if source_policy == "db_only":
            raise MarketDataIncompleteError({code: sorted(days) for code, days in missing.items()})
        self._fill_missing_daily(persisted, missing, providers)
        return persisted

    def _repositories(self) -> tuple[InstrumentRepository, StockRepository]:
        if self.instrument_repository is None:
            self.instrument_repository = InstrumentRepository()
        if self.stock_repository is None:
            self.stock_repository = StockRepository()
        return self.instrument_repository, self.stock_repository

    @staticmethod
    def _stored_bar(row: Any) -> MarketBar:
        market = market_from_value(row.instrument.market)
        return MarketBar(
            symbol=row.instrument.code,
            market=market,
            interval="1d",
            trade_date=row.date,
            bar_time=None,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=int(row.volume),
            amount=None if row.amount is None else float(row.amount),
            currency=currency_for_market(market),
            adjustment=Adjustment.FORWARD,
            provider="database",
        )

    def _load_persisted_daily(
        self, request: DailyBarsRequest
    ) -> tuple[BatchBarResult, dict[str, set[date]]]:
        _, stocks = self._repositories()
        expected = set(
            get_trading_days_between(
                infer_market(request.symbols[0]).value.lower(), request.start_date, request.end_date
            )
        )
        result = BatchBarResult()
        missing: dict[str, set[date]] = {}
        for code in request.symbols:
            rows = stocks.get_range(code, request.start_date, request.end_date)
            bars = [self._stored_bar(row) for row in rows]
            dates = {bar.trade_date for bar in bars}
            if bars:
                result.data[code] = bars
                result.providers_used[code] = "database"
            absent = expected - dates
            if absent:
                missing[code] = absent
        return result, missing

    def _fill_missing_daily(
        self,
        result: BatchBarResult,
        missing: dict[str, set[date]],
        providers: Iterable[str] | None,
    ) -> None:
        groups: dict[tuple[date, date], list[str]] = {}
        for code, dates in missing.items():
            groups.setdefault((min(dates), max(dates)), []).append(code)
        for (start_date, end_date), codes in groups.items():
            remote = self.router.route_daily(
                DailyBarsRequest(tuple(codes), start_date, end_date, Adjustment.FORWARD), providers
            )
            self._persist_remote_daily(remote)
            for code in codes:
                merged = {bar.trade_date: bar for bar in result.data.get(code, [])}
                merged.update({bar.trade_date: bar for bar in remote.data.get(code, [])})
                if merged:
                    result.data[code] = [merged[day] for day in sorted(merged)]
                    result.providers_used[code] = remote.providers_used.get(code, "database")
                remaining = missing[code] - set(merged)
                if remaining:
                    reason = remote.failed_symbols.get(code) or f"missing {len(remaining)} trading days"
                    result.failed_symbols[code] = reason
                else:
                    result.failed_symbols.pop(code, None)

    def _persist_remote_daily(self, result: BatchBarResult) -> None:
        try:
            instruments, stocks = self._repositories()
        except Exception as exc:
            logger.warning("daily bars fetched but persistence is unavailable: %s", exc)
            return
        for code, bars in result.data.items():
            if not bars:
                continue
            instrument = instruments.get_by_code(code)
            if instrument is None:
                info = self.router.route_instruments(InstrumentRequest((code,))).data.get(code)
                if info is None:
                    result.failed_symbols[code] = "instrument metadata unavailable; daily bars were not persisted"
                    continue
                instruments.upsert_symbols(
                    [{"market": info.market.value, "code": code, "name": info.name, "source": info.provider}]
                )
                instrument = instruments.get_by_code(code)
            if instrument is None:
                result.failed_symbols[code] = "instrument could not be persisted"
                continue
            rows = [
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
                for bar in bars
            ]
            stocks.upsert_daily(instrument.id, rows, result.providers_used.get(code, bars[0].provider))

    def get_minute_bars(
        self,
        symbols: Iterable[str],
        start_time: datetime,
        end_time: datetime,
        *,
        interval: str = "1m",
        providers: Iterable[str] | None = None,
    ) -> BatchBarResult:
        request = MinuteBarsRequest(self._canonical_symbols(symbols), start_time, end_time, interval)
        return self.router.route_minute(request, providers)

    def get_realtime_quotes(
        self, symbols: Iterable[str], *, providers: Iterable[str] | None = None
    ) -> BatchQuoteResult:
        return self.router.route_quotes(QuoteRequest(self._canonical_symbols(symbols)), providers)

    def get_market_snapshot(self, market: Market | str, *, providers: Iterable[str] | None = None) -> BatchQuoteResult:
        return self.router.route_market_snapshot(market_from_value(market), providers)

    def get_market_indices(self, market: Market | str, *, providers: Iterable[str] | None = None) -> list[MarketIndex]:
        return self.router.route_indices(market_from_value(market), providers)

    def get_market_stats(self, market: Market | str, *, providers: Iterable[str] | None = None) -> MarketStats | None:
        return self.router.route_market_stats(market_from_value(market), providers)

    def get_sector_rankings(
        self,
        market: Market | str,
        *,
        providers: Iterable[str] | None = None,
        limit: int | None = None,
    ) -> SectorRankings | None:
        result = self.router.route_sector_rankings(market_from_value(market), providers)
        if result is not None and limit is not None:
            return replace(result, top=result.top[:limit], bottom=result.bottom[:limit])
        return result

    def get_instrument_info(
        self, symbols: Iterable[str], *, providers: Iterable[str] | None = None
    ) -> BatchInstrumentResult:
        return self.router.route_instruments(InstrumentRequest(self._canonical_symbols(symbols)), providers)

    def get_chip_distribution(self, symbol: str):
        canonical = canonical_symbol(symbol)
        if infer_market(canonical) is not Market.CN:
            return None
        provider = self.registry.get("akshare").provider
        return provider.get_chip_distribution(canonical)

    def get_belong_boards(self, symbol: str) -> list[dict[str, Any]]:
        canonical = canonical_symbol(symbol)
        if infer_market(canonical) is not Market.CN:
            return []
        provider = self.registry.get("efinance").provider
        frame = provider.get_belong_board(canonical)
        if frame is None:
            return []
        if isinstance(frame, pd.Series):
            return [frame.to_dict()]
        if isinstance(frame, pd.DataFrame):
            return frame.to_dict(orient="records")
        if isinstance(frame, dict):
            return [frame]
        return []

    @staticmethod
    def _context_block(status: str, data: dict[str, Any], provider: str, errors=None) -> dict[str, Any]:
        return {
            "status": status,
            "data": data,
            "source_chain": [{"provider": provider, "result": status, "duration_ms": 0}],
            "errors": list(errors or []),
        }

    def build_failed_fundamental_context(self, symbol: str, reason: str) -> dict[str, Any]:
        blocks = {
            name: self._context_block("failed", {}, "market_data_service", [reason])
            for name in ("valuation", "growth", "earnings", "institution", "capital_flow", "dragon_tiger", "boards")
        }
        return {
            "market": infer_market(canonical_symbol(symbol)).value.lower(),
            "status": "failed",
            "coverage": {name: "failed" for name in blocks},
            "source_chain": [{"provider": "market_data_service", "result": "failed", "duration_ms": 0}],
            "errors": [reason],
            **blocks,
        }

    def get_capital_flow_context(self, symbol: str, budget_seconds: float | None = None) -> dict[str, Any]:
        del budget_seconds
        canonical = canonical_symbol(symbol)
        if infer_market(canonical) is not Market.CN:
            return self._context_block("not_supported", {}, "akshare", ["market not supported"])
        from .fundamental_adapter import AkshareFundamentalAdapter

        payload = AkshareFundamentalAdapter().get_capital_flow(canonical.split(".", 1)[0])
        status = str(payload.get("status") or ("ok" if payload else "not_supported"))
        return self._context_block(status, payload if isinstance(payload, dict) else {}, "akshare")

    def get_dragon_tiger_context(self, symbol: str, budget_seconds: float | None = None) -> dict[str, Any]:
        del budget_seconds
        canonical = canonical_symbol(symbol)
        if infer_market(canonical) is not Market.CN:
            return self._context_block("not_supported", {}, "akshare", ["market not supported"])
        from .fundamental_adapter import AkshareFundamentalAdapter

        payload = AkshareFundamentalAdapter().get_dragon_tiger_flag(canonical.split(".", 1)[0])
        status = str(payload.get("status") or ("ok" if payload else "not_supported"))
        return self._context_block(status, payload if isinstance(payload, dict) else {}, "akshare")

    def get_board_context(self, symbol: str, budget_seconds: float | None = None) -> dict[str, Any]:
        del budget_seconds
        market = infer_market(canonical_symbol(symbol))
        if market is not Market.CN:
            return self._context_block("not_supported", {}, "market_data_service", ["market not supported"])
        rankings = self.get_sector_rankings(market, limit=5)
        if rankings is None:
            return self._context_block("failed", {}, "market_data_service", ["sector rankings unavailable"])
        return self._context_block(
            "ok" if rankings.top and rankings.bottom else "partial",
            {"top": rankings.top, "bottom": rankings.bottom},
            rankings.provider,
        )

    def get_fundamental_context(self, symbol: str, budget_seconds: float | None = None) -> dict[str, Any]:
        canonical = canonical_symbol(symbol)
        market = infer_market(canonical)
        if market is not Market.CN:
            return self.build_failed_fundamental_context(canonical, "market not supported")
        try:
            quote_result = self.get_realtime_quotes([canonical])
            quote = quote_result.data.get(canonical)
            valuation_data = {
                "pe_ratio": quote.pe_ratio if quote else None,
                "pb_ratio": quote.pb_ratio if quote else None,
                "total_mv": quote.total_mv if quote else None,
                "circ_mv": quote.circ_mv if quote else None,
            }
            valuation = self._context_block(
                "ok" if any(value is not None for value in valuation_data.values()) else "partial",
                valuation_data,
                quote.provider if quote else "market_data_service",
            )
            from .fundamental_adapter import AkshareFundamentalAdapter

            bundle = AkshareFundamentalAdapter().get_fundamental_bundle(canonical.split(".", 1)[0])
            bundle_status = str(bundle.get("status") or "partial")
            growth = self._context_block(
                bundle_status, dict(bundle.get("growth") or {}), "akshare", bundle.get("errors")
            )
            earnings = self._context_block(
                bundle_status, dict(bundle.get("earnings") or {}), "akshare", bundle.get("errors")
            )
            institution = self._context_block(
                bundle_status, dict(bundle.get("institution") or {}), "akshare", bundle.get("errors")
            )
            capital_flow = self.get_capital_flow_context(canonical, budget_seconds)
            dragon_tiger = self.get_dragon_tiger_context(canonical, budget_seconds)
            boards = self.get_board_context(canonical, budget_seconds)
            blocks = {
                "valuation": valuation,
                "growth": growth,
                "earnings": earnings,
                "institution": institution,
                "capital_flow": capital_flow,
                "dragon_tiger": dragon_tiger,
                "boards": boards,
            }
            statuses = {name: block["status"] for name, block in blocks.items()}
            return {
                "market": "cn",
                "status": "ok" if all(value == "ok" for value in statuses.values()) else "partial",
                "coverage": statuses,
                "source_chain": [item for block in blocks.values() for item in block["source_chain"]],
                "errors": [item for block in blocks.values() for item in block["errors"]],
                **blocks,
            }
        except Exception as exc:
            return self.build_failed_fundamental_context(canonical, str(exc))


__all__ = ["MarketDataService", "build_default_registry"]
