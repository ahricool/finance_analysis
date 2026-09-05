"""Deterministic capability routing with ordered fallback."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Callable, Iterable, TypeVar

from .config import provider_order
from .models import (
    BatchBarResult,
    BatchInstrumentResult,
    BatchQuoteResult,
    DailyBarsRequest,
    InstrumentRequest,
    Market,
    MarketIndex,
    MarketStats,
    MinuteBarsRequest,
    QuoteRequest,
    SectorRankings,
)
from .normalizer import infer_market
from .registry import (
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
                break
            provider_request = replace(request, symbols=tuple(pending))
            try:
                provider_result = getattr(registration.provider, method_name)(provider_request)
            except Exception as exc:
                logger.warning("provider=%s capability=%s failed: %s", registration.name, capability, exc)
                for symbol in pending:
                    errors[symbol].append(f"{registration.name}: {exc}")
                    result.request_errors[symbol] = f"{registration.name}: {exc}"
                continue
            next_pending: list[str] = []
            for symbol in pending:
                failure = provider_result.request_errors.get(symbol) or provider_result.failed_symbols.get(symbol)
                if failure:
                    result.request_errors[symbol] = f"{registration.name}: {failure}"
                try:
                    bars = validate_bars(provider_result.data.get(symbol, []))
                    if capability == DAILY_BARS and any(bar.adjustment is not request.adjustment for bar in bars):
                        raise ValueError(
                            f"provider returned {bars[0].adjustment.value} bars for "
                            f"requested adjustment={request.adjustment.value}"
                        )
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
        for symbol in pending:
            if errors[symbol]:
                result.failed_symbols[symbol] = "; ".join(errors[symbol])
            else:
                result.missing_symbols.append(symbol)
        return result

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

    def route_sector_rankings(self, market: Market, providers: Iterable[str] | None = None) -> SectorRankings | None:
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
