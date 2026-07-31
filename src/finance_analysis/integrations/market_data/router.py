"""Deterministic capability routing with ordered fallback."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from typing import Callable, Iterable, TypeVar
from zoneinfo import ZoneInfo

from .config import provider_order
from .models import (
    AdjustmentRequest,
    Adjustment,
    AdjustmentResult,
    BatchBarResult,
    BatchInstrumentResult,
    BatchQuoteResult,
    DailyBarsRequest,
    InstrumentRequest,
    Market,
    MarketBar,
    MarketIndex,
    MarketStats,
    MinuteBarsRequest,
    QuoteRequest,
    SectorRankings,
)
from .normalizer import infer_market
from .registry import (
    ADJUSTMENT_FACTORS,
    DAILY_BARS,
    INSTRUMENT_INFO,
    LATEST_MARKET_SNAPSHOT,
    MARKET_INDICES,
    MARKET_STATS,
    MINUTE_BARS,
    REALTIME_QUOTES,
    SECTOR_RANKINGS,
    ProviderConfigurationError,
    ProviderRegistration,
    ProviderRegistry,
)
from .validator import validate_bars, validate_quote

logger = logging.getLogger(__name__)
T = TypeVar("T")


class MarketDataRouter:
    def __init__(self, registry: ProviderRegistry):
        self.registry = registry

    def _providers(
        self,
        *,
        market: Market,
        capability: str,
        providers: Iterable[str] | None,
    ) -> tuple[ProviderRegistration, ...]:
        if providers is not None:
            requested = tuple(providers)
            if not requested:
                raise ProviderConfigurationError("providers override must not be empty")
            return self.registry.resolve(requested, capability)
        available = set(self.registry.names())
        registrations = []
        for name in provider_order(market, capability):
            if name in available and capability in self.registry.capabilities(name):
                registrations.append(self.registry.get(name))
        if not registrations:
            raise ProviderConfigurationError(
                f"no registered provider supports market={market.value}, capability={capability}"
            )
        return tuple(registrations)

    @staticmethod
    def _market_for_symbols(symbols: tuple[str, ...]) -> Market:
        markets = {infer_market(symbol) for symbol in symbols}
        if len(markets) != 1:
            raise ProviderConfigurationError("one request cannot mix symbols from different markets")
        return markets.pop()

    def route_daily(self, request: DailyBarsRequest, providers: Iterable[str] | None = None) -> BatchBarResult:
        return self._route_bars(request, DAILY_BARS, "fetch_daily_bars", providers)

    def route_minute(self, request: MinuteBarsRequest, providers: Iterable[str] | None = None) -> BatchBarResult:
        return self._route_bars(request, MINUTE_BARS, "fetch_minute_bars", providers)

    def _route_bars(self, request, capability: str, method_name: str, providers) -> BatchBarResult:
        market = self._market_for_symbols(request.symbols)
        registrations = self._providers(market=market, capability=capability, providers=providers)
        pending = list(request.symbols)
        result = BatchBarResult()
        errors: dict[str, list[str]] = {symbol: [] for symbol in request.symbols}
        for registration in registrations:
            if not pending:
                if capability == DAILY_BARS and providers is None and market is Market.CN:
                    if registration.name == "pytdx":
                        pending = self._fill_cn_latest_from_snapshot(request, pending, result, errors)
                        break
                    continue
                break
            provider_request = replace(request, symbols=tuple(pending))
            try:
                provider_result = getattr(registration.provider, method_name)(provider_request)
            except Exception as exc:
                logger.warning("provider=%s capability=%s failed: %s", registration.name, capability, exc)
                for symbol in pending:
                    errors[symbol].append(f"{registration.name}: {exc}")
                continue
            next_pending: list[str] = []
            for symbol in pending:
                try:
                    bars = validate_bars(provider_result.data.get(symbol, []))
                except Exception as exc:
                    errors[symbol].append(f"{registration.name}: {exc}")
                    next_pending.append(symbol)
                    continue
                if bars:
                    result.data[symbol] = bars
                    result.providers_used[symbol] = registration.name
                else:
                    reason = provider_result.failed_symbols.get(symbol)
                    if reason:
                        errors[symbol].append(f"{registration.name}: {reason}")
                    next_pending.append(symbol)
            pending = next_pending
            if (
                capability == DAILY_BARS
                and providers is None
                and market is Market.CN
                and registration.name == "pytdx"
            ):
                pending = self._fill_cn_latest_from_snapshot(request, pending, result, errors)
        for symbol in pending:
            if errors[symbol]:
                result.failed_symbols[symbol] = "; ".join(errors[symbol])
            else:
                result.missing_symbols.append(symbol)
        return result

    def _fill_cn_latest_from_snapshot(self, request, pending, result, errors) -> list[str]:
        """Use one Efinance full-market snapshot between PyTDX and BaoStock."""
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        if not (request.start_date <= today <= request.end_date):
            return pending
        candidates = [
            symbol
            for symbol in request.symbols
            if not result.data.get(symbol) or max(bar.trade_date for bar in result.data[symbol]) < today
        ]
        if not candidates:
            return pending
        try:
            registration = self.registry.resolve(("efinance",), LATEST_MARKET_SNAPSHOT)[0]
            snapshot = registration.provider.fetch_market_snapshot(Market.CN)
        except Exception as exc:
            for symbol in candidates:
                errors[symbol].append(f"efinance_snapshot: {exc}")
            return pending
        remaining = list(pending)
        for symbol in candidates:
            quote = snapshot.data.get(symbol)
            prices = (quote.open_price, quote.high, quote.low, quote.price) if quote is not None else ()
            if (
                quote is None
                or quote.quote_time is None
                or quote.volume is None
                or any(value is None for value in prices)
            ):
                continue
            trade_date = quote.quote_time.astimezone(ZoneInfo("Asia/Shanghai")).date()
            existing = result.data.get(symbol, [])
            if not (request.start_date <= trade_date <= request.end_date) or (
                existing and max(bar.trade_date for bar in existing) >= trade_date
            ):
                continue
            try:
                bars = validate_bars(
                    [
                        MarketBar(
                            symbol=symbol,
                            market=Market.CN,
                            interval="1d",
                            trade_date=trade_date,
                            bar_time=None,
                            open=float(quote.open_price),
                            high=float(quote.high),
                            low=float(quote.low),
                            close=float(quote.price),
                            volume=int(quote.volume),
                            amount=quote.amount,
                            currency=quote.currency,
                            adjustment=Adjustment.RAW,
                            provider="efinance",
                        )
                    ]
                )
            except Exception as exc:
                errors[symbol].append(f"efinance_snapshot: {exc}")
                continue
            result.data[symbol] = sorted([*existing, *bars], key=lambda bar: bar.trade_date)
            result.providers_used[symbol] = "efinance"
            if symbol in remaining:
                remaining.remove(symbol)
        return remaining

    def route_quotes(self, request: QuoteRequest, providers: Iterable[str] | None = None) -> BatchQuoteResult:
        market = self._market_for_symbols(request.symbols)
        registrations = self._providers(market=market, capability=REALTIME_QUOTES, providers=providers)
        pending = list(request.symbols)
        result = BatchQuoteResult()
        errors: dict[str, list[str]] = {symbol: [] for symbol in request.symbols}
        for registration in registrations:
            if not pending:
                break
            try:
                provider_result = registration.provider.fetch_quotes(QuoteRequest(tuple(pending)))
            except Exception as exc:
                logger.warning("provider=%s capability=%s failed: %s", registration.name, REALTIME_QUOTES, exc)
                for symbol in pending:
                    errors[symbol].append(f"{registration.name}: {exc}")
                continue
            next_pending = []
            for symbol in pending:
                quote = provider_result.data.get(symbol)
                if quote is not None:
                    try:
                        result.data[symbol] = validate_quote(quote)
                        result.providers_used[symbol] = registration.name
                    except Exception as exc:
                        errors[symbol].append(f"{registration.name}: {exc}")
                        next_pending.append(symbol)
                else:
                    reason = provider_result.failed_symbols.get(symbol)
                    if reason:
                        errors[symbol].append(f"{registration.name}: {reason}")
                    next_pending.append(symbol)
            pending = next_pending
        for symbol in pending:
            if errors[symbol]:
                result.failed_symbols[symbol] = "; ".join(errors[symbol])
            else:
                result.missing_symbols.append(symbol)
        return result

    def route_market_snapshot(self, market: Market, providers: Iterable[str] | None = None) -> BatchQuoteResult:
        registrations = self._providers(market=market, capability=LATEST_MARKET_SNAPSHOT, providers=providers)
        errors = []
        for registration in registrations:
            try:
                result = registration.provider.fetch_market_snapshot(market)
                if result.data:
                    validated = {}
                    for symbol, quote in result.data.items():
                        try:
                            validated[symbol] = validate_quote(quote)
                        except Exception as exc:
                            result.failed_symbols[symbol] = str(exc)
                    result.data = validated
                    if result.data:
                        return result
                errors.append(f"{registration.name}: empty snapshot")
            except Exception as exc:
                errors.append(f"{registration.name}: {exc}")
        return BatchQuoteResult(failed_symbols={market.value: "; ".join(errors)})

    def route_indices(self, market: Market, providers: Iterable[str] | None = None) -> list[MarketIndex]:
        return self._route_overview(market, MARKET_INDICES, "get_indices", providers)

    def route_market_stats(self, market: Market, providers: Iterable[str] | None = None) -> MarketStats | None:
        return self._route_overview(market, MARKET_STATS, "get_market_stats", providers)

    def route_sector_rankings(
        self, market: Market, providers: Iterable[str] | None = None
    ) -> SectorRankings | None:
        return self._route_overview(market, SECTOR_RANKINGS, "get_sector_rankings", providers)

    def _route_overview(self, market: Market, capability: str, method_name: str, providers):
        registrations = self._providers(market=market, capability=capability, providers=providers)
        for registration in registrations:
            try:
                value = getattr(registration.provider, method_name)(market)
                if value:
                    return value
            except Exception as exc:
                logger.warning("provider=%s capability=%s failed: %s", registration.name, capability, exc)
        return [] if capability == MARKET_INDICES else None

    def route_instruments(
        self, request: InstrumentRequest, providers: Iterable[str] | None = None
    ) -> BatchInstrumentResult:
        market = self._market_for_symbols(request.symbols)
        registrations = self._providers(market=market, capability=INSTRUMENT_INFO, providers=providers)
        pending = list(request.symbols)
        result = BatchInstrumentResult()
        errors: dict[str, list[str]] = {symbol: [] for symbol in request.symbols}
        for registration in registrations:
            if not pending:
                break
            try:
                provider_result = registration.provider.get_instrument_info(InstrumentRequest(tuple(pending)))
            except Exception as exc:
                for symbol in pending:
                    errors[symbol].append(f"{registration.name}: {exc}")
                continue
            next_pending = []
            for symbol in pending:
                info = provider_result.data.get(symbol)
                if info is not None and info.name.strip():
                    result.data[symbol] = info
                    result.providers_used[symbol] = registration.name
                else:
                    reason = provider_result.failed_symbols.get(symbol)
                    if reason:
                        errors[symbol].append(f"{registration.name}: {reason}")
                    next_pending.append(symbol)
            pending = next_pending
        for symbol in pending:
            if errors[symbol]:
                result.failed_symbols[symbol] = "; ".join(errors[symbol])
            else:
                result.missing_symbols.append(symbol)
        return result

    def route_adjustments(
        self, request: AdjustmentRequest, providers: Iterable[str] | None = None
    ) -> AdjustmentResult:
        market = self._market_for_symbols(request.symbols)
        registrations = self._providers(market=market, capability=ADJUSTMENT_FACTORS, providers=providers)
        pending = list(request.symbols)
        result = AdjustmentResult()
        errors: dict[str, list[str]] = {symbol: [] for symbol in request.symbols}
        for registration in registrations:
            if not pending:
                break
            try:
                provider_result = registration.provider.get_adjustment_factors(replace(request, symbols=tuple(pending)))
            except Exception as exc:
                for symbol in pending:
                    errors[symbol].append(f"{registration.name}: {exc}")
                continue
            next_pending = []
            for symbol in pending:
                factors = provider_result.factors.get(symbol, [])
                if factors:
                    result.factors[symbol] = factors
                    result.corporate_actions[symbol] = provider_result.corporate_actions.get(symbol, [])
                    result.providers_used[symbol] = registration.name
                else:
                    reason = provider_result.failed_symbols.get(symbol)
                    if reason:
                        errors[symbol].append(f"{registration.name}: {reason}")
                    next_pending.append(symbol)
            pending = next_pending
        for symbol in pending:
            if errors[symbol]:
                result.failed_symbols[symbol] = "; ".join(errors[symbol])
            else:
                result.missing_symbols.append(symbol)
        return result
