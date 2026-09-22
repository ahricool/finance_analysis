"""The only market-data entry point used by business code."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable, Literal

import pandas as pd

from finance_analysis.core.time import utc_now  # pragma: allowlist secret
from finance_analysis.database.repositories.stock import InstrumentRepository, StockRepository  # pragma: allowlist secret
from finance_analysis.market_review.trading_calendar import get_completed_trading_days, get_market_now  # pragma: allowlist secret

from .config import DataProviderConfig, US_DAILY_SYNC_PROVIDERS, get_data_provider_config
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
    MarketQuote,
    MarketStats,
    MinuteBarsRequest,
    QuoteRequest,
    SectorRankings,
    adjustment_from_value,
    market_from_value,
)
from .normalizer import bars_from_frame, canonical_symbol, currency_for_market, infer_market, quote_from_value
from .registry import (
    DRAGON_TIGER_BOARD,
    LIMIT_UP_POOL,
    LIMIT_DOWN_POOL,
    LIMIT_BREAK_POOL,
    LIMIT_UP_LADDER,
    INDUSTRY_CATALOG,
    INDEX_QUOTES,
    INDEX_HISTORY,
    INDEX_CONSTITUENTS,
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
from .request_budget import BudgetExhausted, check_budget, remaining_seconds, request_budget
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
        if request.interval != "1m":
            raise ValueError("streaming minute bars are 1m only; refusing to relabel as " + request.interval)
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
    from .providers.alpaca import AlpacaProvider
    from .providers.fuyao import FuyaoProvider
    from .providers.easyquotation import EasyQuotationProvider
    from .providers.tickflow import TickFlowFreeProvider
    from .providers.yfinance import YFinanceProvider
    from .providers.sina_minute import SinaMinuteProvider

    resolved_config = config or get_data_provider_config()
    registry = ProviderRegistry()
    registry.register(
        "alpaca",
        AlpacaProvider(api_key=resolved_config.alpaca_api_key, secret_key=resolved_config.alpaca_secret_key),
        capabilities={DAILY_BARS},
    )
    registry.register_internal("database", _DatabaseInstrumentProvider(instrument_repository), capabilities={INSTRUMENT_INFO})
    registry.register_internal(
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
        "fuyao",
        FuyaoProvider(api_key=resolved_config.fuyao_api_key, timeout=resolved_config.fuyao_timeout_seconds),
        capabilities={DAILY_BARS, REALTIME_QUOTES, LATEST_MARKET_SNAPSHOT, MARKET_INDICES,
                      MARKET_STATS, SECTOR_RANKINGS, INSTRUMENT_INFO,
                      INDUSTRY_CATALOG, INDEX_HISTORY, INDEX_CONSTITUENTS, INDEX_QUOTES,
                      LIMIT_UP_POOL, LIMIT_DOWN_POOL, LIMIT_BREAK_POOL, LIMIT_UP_LADDER, DRAGON_TIGER_BOARD},
    )
    registry.register(
        "easyquotation",
        EasyQuotationProvider(),
        capabilities={LATEST_MARKET_SNAPSHOT},
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
    registry.register(
        "sina_minute",
        SinaMinuteProvider(),
        capabilities={MINUTE_BARS},
    )
    from .providers.longbridge.market import LongbridgeProvider

    registry.register(
        "longbridge",
        LongbridgeProvider(),
        capabilities={DAILY_BARS, MINUTE_BARS, REALTIME_QUOTES, MARKET_INDICES, INSTRUMENT_INFO},
    )
    return registry


class MarketDataService:
    def get_dragon_tiger_board(self, trade_date, board_type="all", market="CN"):
        with request_budget(120):
            return self.router.route_market_pool(market, DRAGON_TIGER_BOARD, trade_date, board_type)

    def get_limit_up_pool(self, trade_date, market="CN"):
        with request_budget(120):
            return self.router.route_market_pool(market, LIMIT_UP_POOL, trade_date)

    def get_limit_down_pool(self, trade_date, market="CN"):
        with request_budget(120):
            return self.router.route_market_pool(market, LIMIT_DOWN_POOL, trade_date)

    def get_limit_break_pool(self, trade_date, market="CN"):
        with request_budget(120):
            return self.router.route_market_pool(market, LIMIT_BREAK_POOL, trade_date)

    def get_limit_up_ladder(self, market="CN"):
        with request_budget(120):
            return self.router.route_market_pool(market, LIMIT_UP_LADDER)

    def get_industry_catalog(self, market="CN"):
        return self.router.route_index_reference(market, INDUSTRY_CATALOG)

    def get_index_quotes(self, codes, market="CN"):
        return self.router.route_index_reference(market, INDEX_QUOTES, codes)

    def get_index_history(self, code, start, end, market="CN"):
        return self.router.route_index_reference(market, INDEX_HISTORY, code, start, end)

    def get_index_constituents(self, code, market="CN"):
        return self.router.route_index_reference(market, INDEX_CONSTITUENTS, code)

    def get_calendar_sources(self):
        """Fresh adapters per sync; Yahoo batch cache is shared across markets."""
        from .providers.longbridge.calendar import LongbridgeCalendarFetcher
        from .providers.yfinance_calendar import YFinanceCalendarFetcher

        return {"yfinance": YFinanceCalendarFetcher(), "longbridge": LongbridgeCalendarFetcher()}

    def __init__(
        self,
        registry: ProviderRegistry | None = None,
        *,
        config: DataProviderConfig | None = None,
        instrument_repository: InstrumentRepository | None = None,
        stock_repository: StockRepository | None = None,
        streaming_source: Any = None,
        daily_sync: bool = False,
    ) -> None:
        self.daily_sync = daily_sync
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
        source_policy: Literal["db_only", "db_first", "db_latest", "db_fresh", "remote_only"] = "db_first",
    ) -> BatchBarResult:
        """Prefer existing local history, otherwise return remote bars without writes.

        db_first trusts any local history; db_fresh refreshes only stale tails.
        db_latest trusts DB only when the expected completed session exists;
        otherwise providers serve the whole requested window in memory only.
        Only explicit maintenance jobs persist daily history. Local existence is
        not a trading-calendar completeness claim (suspensions and IPOs have gaps).
        """
        canonical = self._canonical_symbols(symbols)
        requested_adjustment = adjustment_from_value(adjustment)
        if requested_adjustment is not Adjustment.FORWARD:
            raise ValueError("Daily bars are stored and served only as forward-adjusted prices")
        if source_policy not in {"db_only", "db_first", "db_latest", "db_fresh", "remote_only"}:
            raise ValueError("source_policy must be db_only, db_first, db_latest, db_fresh, or remote_only")
        if not canonical:
            return BatchBarResult()
        request = DailyBarsRequest(canonical, start_date, end_date, Adjustment.FORWARD)
        if source_policy == "db_only":
            # One bulk history query, with no existence probes or provider routing.
            _, stocks = self._repositories()
            histories = stocks.get_daily_ranges(canonical, start_date, end_date)
            data = {code: [self._stored_bar(row) for row in rows] for code, rows in histories.items() if rows}
            return BatchBarResult(
                data=data,
                providers_used={code: "database" for code in data},
                missing_symbols=[code for code in canonical if code not in data],
            )
        if source_policy == "remote_only":
            if self.daily_sync and all(infer_market(code) is Market.US for code in canonical):
                return self.router.route_daily(request, providers or US_DAILY_SYNC_PROVIDERS, complete_fallback=True)
            return self.router.route_daily(request, providers)
        if source_policy == "db_fresh":
            return self._get_fresh_daily(request, providers)
        try:
            result, missing = (
                self._load_latest_daily(request) if source_policy == "db_latest" else self._load_persisted_daily(request)
            )
        except Exception:
            logger.warning("Database daily bars unavailable; falling back to providers: %s", canonical, exc_info=True)
            return self.router.route_daily(request, providers)
        if missing and source_policy in {"db_first", "db_latest"}:
            remote = self.router.route_daily(replace(request, symbols=tuple(missing)), providers)
            result.data.update(remote.data)
            result.providers_used.update(remote.providers_used)
            result.failed_symbols.update(remote.failed_symbols)
            result.request_errors.update(remote.request_errors)
            result.missing_symbols.extend(remote.missing_symbols)
        elif missing:
            result.missing_symbols.extend(missing)
        return result

    def _load_latest_daily(self, request: DailyBarsRequest) -> tuple[BatchBarResult, list[str]]:
        """Daily K HTTP API is read-only: trust DB as-is if its expected session exists.

        Freshness is ONLY the latest completed trading day on or before end_date.
        Do not check historical gaps. Missing/stale DB falls back to providers for
        this request only, never to database synchronization or persistence.
        """
        _, stocks = self._repositories()
        result = BatchBarResult()
        missing: list[str] = []
        now = utc_now()
        for code in request.symbols:
            market = infer_market(code).value.lower()
            market_now = get_market_now(market, now)
            # Historical requests use that market's end-of-day; today/future
            # requests are capped at now so an unfinished session is not required.
            cutoff = min(market_now, datetime.combine(request.end_date, time.max, tzinfo=market_now.tzinfo))
            expected = get_completed_trading_days(market, 1, cutoff)[-1]
            # Also probe expected when the requested window starts on a weekend
            # or after now. Never include that extra probe date in the response.
            rows = stocks.get_range(code, min(request.start_date, expected), request.end_date)
            if not any(row.date == expected for row in rows):
                missing.append(code)
                continue
            result.providers_used[code] = "database"
            result.data[code] = [self._stored_bar(row) for row in rows if row.date >= request.start_date]
        return result, missing

    def _get_fresh_daily(self, request: DailyBarsRequest, providers: Iterable[str] | None) -> BatchBarResult:
        """Read history and batch-refresh stale tails, without gap checks or writes."""
        instruments, stocks = self._repositories()
        identities = instruments.get_by_codes(request.symbols)
        latest_dates = stocks.latest_daily_dates(instrument.id for instrument in identities.values())
        histories = stocks.get_daily_ranges(request.symbols, request.start_date, request.end_date)
        result = BatchBarResult()
        missing = []
        stale = []
        tail_start = request.end_date
        for code in request.symbols:
            instrument = identities.get(code)
            latest = latest_dates.get(instrument.id) if instrument is not None else None
            if latest is None:
                missing.append(code)
                continue
            bars = [self._stored_bar(row) for row in histories.get(code, [])]
            if bars:
                result.data[code] = bars
                result.providers_used[code] = "database"
            if latest < request.end_date:
                stale.append(code)
                tail_start = min(tail_start, max(request.start_date, latest - timedelta(days=10)))
        # Two batches at most: new histories and stale tails. A shared tail start
        # preserves provider batching even when local latest dates differ.
        selected_providers = tuple(providers) if providers is not None else None
        for codes, start in ((missing, request.start_date), (stale, tail_start)):
            if not codes:
                continue
            remote = self.router.route_daily(
                replace(request, symbols=tuple(codes), start_date=start), selected_providers
            )
            for code, bars in remote.data.items():
                merged = {bar.trade_date: bar for bar in result.data.get(code, [])}
                merged.update(
                    {bar.trade_date: bar for bar in bars if request.start_date <= bar.trade_date <= request.end_date}
                )
                if merged:
                    result.data[code] = [merged[day] for day in sorted(merged)]
            result.providers_used.update(remote.providers_used)
            result.failed_symbols.update(remote.failed_symbols)
            result.request_errors.update(remote.request_errors)
        result.missing_symbols = [code for code in request.symbols if not result.data.get(code)]
        return result

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

    def _load_persisted_daily(self, request: DailyBarsRequest) -> tuple[BatchBarResult, list[str]]:
        instruments, stocks = self._repositories()
        result = BatchBarResult()
        missing: list[str] = []
        for code in request.symbols:
            instrument = instruments.get_by_code(code)
            if instrument is None or not stocks.has_daily_data(instrument.id):
                missing.append(code)
                continue
            rows = stocks.get_range(code, request.start_date, request.end_date)
            bars = [self._stored_bar(row) for row in rows]
            if bars:
                result.data[code] = bars
                result.providers_used[code] = "database"
            else:
                result.missing_symbols.append(code)
        return result, missing

    def get_minute_bars(
        self,
        symbols: Iterable[str],
        start_time: datetime,
        end_time: datetime,
        *,
        interval: str = "1m",
        providers: Iterable[str] | None = None,
        period: str | None = None,
    ) -> BatchBarResult:
        request = MinuteBarsRequest(
            self._canonical_symbols(symbols),
            start_time,
            end_time,
            interval,
            period=period,
        )
        return self.router.route_minute(request, providers)

    def get_realtime_quotes(
        self, symbols: Iterable[str], *, providers: Iterable[str] | None = None
    ) -> BatchQuoteResult:
        return self.router.route_quotes(QuoteRequest(self._canonical_symbols(symbols)), providers)

    def get_intraday_daily_bar(
        self, symbol: str, start_date: date, end_date: date, *, now: datetime | None = None
    ) -> MarketBar | None:
        """Read-only chart overlay; invalid or unavailable quotes fall through per provider."""
        from finance_analysis.market_review.trading_calendar import get_trading_days_between
        from finance_analysis.market_stream.config import market_trading_date

        from .validator import validate_bars

        code = canonical_symbol(symbol)
        market = infer_market(code)
        providers = {
            Market.CN: ("fuyao", "longbridge"),
            Market.US: ("yfinance", "longbridge"),
        }.get(market)
        if providers is None:
            return None
        try:
            today = market_trading_date(now or utc_now(), market.value)
            if not start_date <= today <= end_date:
                return None
            if today not in get_trading_days_between(market.value.lower(), today, today):
                return None
        except Exception:
            logger.warning("Intraday daily calendar unavailable: %s", code, exc_info=True)
            return None
        # Route separately so chart-specific freshness/OHLC rejection also falls back.
        for provider in providers:
            try:
                quote = self.get_realtime_quotes([code], providers=(provider,)).data.get(code)
                if quote is None or quote.quote_time is None:
                    continue
                if market_trading_date(quote.quote_time, market.value) != today:
                    continue
                if (
                    quote.open_price is None or quote.high is None or quote.low is None
                    or quote.price is None or quote.volume is None
                ):
                    continue
                bar = MarketBar(
                    symbol=code,
                    market=market,
                    interval="1d",
                    trade_date=today,
                    bar_time=None,
                    open=quote.open_price,
                    high=quote.high,
                    low=quote.low,
                    close=quote.price,
                    volume=quote.volume,
                    amount=quote.amount,
                    currency=quote.currency,
                    adjustment=Adjustment.FORWARD,
                    provider=quote.provider,
                )
                return validate_bars([bar])[0]
            except Exception:
                logger.warning("Intraday daily quote unavailable: %s provider=%s", code, provider, exc_info=True)
        return None

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

    def get_index_members(self, index_code: str) -> list[dict[str, Any]]:
        return self.registry.get("fuyao").provider.fetch_index_members(index_code)

    def _fundamental_adapter(self):
        from .fundamental_adapter import FuyaoFundamentalAdapter

        return FuyaoFundamentalAdapter(self.registry.get("fuyao").provider)

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
        return self._context_block("not_supported", {}, "fuyao", ["public capital-flow API unavailable"])

    def get_dragon_tiger_context(self, symbol: str, budget_seconds: float | None = None) -> dict[str, Any]:
        canonical = canonical_symbol(symbol)
        if infer_market(canonical) is not Market.CN:
            return self._context_block("not_supported", {}, "fuyao", ["market not supported"])
        with request_budget(budget_seconds):
            payload = self._fundamental_adapter().get_dragon_tiger_flag(canonical)
        return self._context_block(payload["status"], payload, "fuyao", payload.get("errors"))

    def get_board_context(self, symbol: str, budget_seconds: float | None = None) -> dict[str, Any]:
        market = infer_market(canonical_symbol(symbol))
        if market is not Market.CN:
            return self._context_block("not_supported", {}, "market_data_service", ["market not supported"])
        try:
            with request_budget(budget_seconds):
                rankings = self.get_sector_rankings(market, limit=5)
                if rankings is None:
                    check_budget()
                    return self._context_block("failed", {}, "market_data_service", ["sector rankings unavailable"])
        except BudgetExhausted:
            return self._context_block("skipped_budget", {}, "fuyao", ["skipped_budget"])
        return self._context_block(
            "ok" if rankings.top and rankings.bottom else "partial",
            {"top": rankings.top, "bottom": rankings.bottom},
            rankings.provider,
        )

    def get_fundamental_context(
        self, symbol: str, budget_seconds: float | None = None, *, realtime_quote: MarketQuote | None = None
    ) -> dict[str, Any]:
        with request_budget(budget_seconds):
            return self._get_fundamental_context(symbol, budget_seconds, realtime_quote)

    def _get_fundamental_context(
        self, symbol: str, budget_seconds: float | None, quote: MarketQuote | None
    ) -> dict[str, Any]:
        canonical = canonical_symbol(symbol)
        market = infer_market(canonical)
        if market is not Market.CN:
            return self.build_failed_fundamental_context(canonical, "market not supported")
        try:
            bundle = self._fundamental_adapter().get_fundamental_bundle(canonical)
        except Exception as exc:
            bundle = {"errors": [str(exc)]}
        blocks = {}
        for name in ("valuation", "growth", "earnings"):
            data = dict(bundle.get(name) or {})
            has_values = any(value is not None for value in data.values())
            blocks[name] = self._context_block(
                "partial" if has_values else ("skipped_budget" if bundle.get("skipped_budget") else "failed"),
                data, "fuyao", bundle.get("errors")
            )
        # Retain existing quote-source preference for fields it already supplies.
        try:
            # The quote chain includes SDKs without deadline support. Do not launch
            # it inside a bounded enrichment stage; Fuyao valuation remains available.
            if quote is None:
                if budget_seconds is not None:
                    raise BudgetExhausted()
                quote = self.get_realtime_quotes([canonical]).data.get(canonical)
            if quote:
                for field in ("pe_ratio", "pb_ratio", "total_mv", "circ_mv"):
                    value = getattr(quote, field)
                    if value is not None:
                        blocks["valuation"]["data"][field] = value
                blocks["valuation"]["source_chain"].append(
                    {"provider": quote.provider, "result": "partial", "duration_ms": 0}
                )
                if any(v is not None for v in blocks["valuation"]["data"].values()):
                    blocks["valuation"]["status"] = "partial"
        except Exception as exc:
            blocks["valuation"]["errors"].append(str(exc))
        blocks["institution"] = self._context_block(
            "not_supported", {}, "fuyao", ["public institution/holder-change API unavailable"]
        )
        blocks["capital_flow"] = self.get_capital_flow_context(canonical)
        for name, fetch in (("dragon_tiger", self.get_dragon_tiger_context), ("boards", self.get_board_context)):
            try:
                check_budget()
                blocks[name] = fetch(canonical, remaining_seconds())
            except BudgetExhausted:
                blocks[name] = self._context_block("skipped_budget", {}, "fuyao", ["skipped_budget"])
            except Exception as exc:
                blocks[name] = self._context_block("failed", {}, "fuyao", [str(exc)])
        statuses = {name: block["status"] for name, block in blocks.items()}
        return {
            "market": "cn",
            "status": (
                "partial" if any(s in {"partial", "ok", "skipped_budget"} for s in statuses.values()) else "failed"
            ),
            "coverage": statuses,
            "source_chain": [item for block in blocks.values() for item in block["source_chain"]],
            "errors": [item for block in blocks.values() for item in block["errors"]], **blocks,
        }


__all__ = ["MarketDataService", "build_default_registry"]
