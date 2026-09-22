"""Deterministic capability routing with ordered fallback."""

from __future__ import annotations

import logging
from dataclasses import replace
from time import monotonic
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
    CAPABILITY_METHODS,
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
    def route_market_pool(self, market, capability, *args):
        if str(getattr(market, "value", market)).upper() != "CN":
            raise ValueError("Market sentiment supports CN only")
        registrations = self._providers(market=Market.CN, capability=capability, providers=None)
        return getattr(registrations[0].provider, CAPABILITY_METHODS[capability])(*args)

    def route_index_reference(self, market, capability, *args):
        # These index capabilities have no stock adjustment semantics or implicit DB writes.
        if str(getattr(market, "value", market)).upper() != "CN":
            raise ValueError("Index reference capabilities support A shares only")
        registrations = self._providers(market=Market.CN, capability=capability, providers=None)
        return getattr(registrations[0].provider, CAPABILITY_METHODS[capability])(*args)

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
        available = set(self.registry.names(include_internal=True))
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

    def route_daily(
        self, request: DailyBarsRequest, providers: Iterable[str] | None = None, *, complete_fallback: bool = False,
    ) -> BatchBarResult:
        return self._route_bars(request, DAILY_BARS, "fetch_daily_bars", providers, complete_fallback=complete_fallback)

    def route_minute(self, request: MinuteBarsRequest, providers: Iterable[str] | None = None) -> BatchBarResult:
        return self._route_bars(request, MINUTE_BARS, "fetch_minute_bars", providers)

    def _route_bars(self, request, capability: str, method_name: str, providers, *, complete_fallback=False) -> BatchBarResult:
        market = self._market_for_symbols(request.symbols)
        registrations = self._providers(market=market, capability=capability, providers=providers)
        pending = list(request.symbols)
        result = BatchBarResult()
        errors: dict[str, list[str]] = {symbol: [] for symbol in request.symbols}
        for registration in registrations:
            if not pending:
                break
            provider_request = replace(request, symbols=tuple(pending))
            started = monotonic()
            try:
                provider_result = getattr(registration.provider, method_name)(provider_request)
            except Exception as exc:
                logger.warning("provider=%s capability=%s failed: %s", registration.name, capability, exc)
                for symbol in pending:
                    errors[symbol].append(f"{registration.name}: {exc}")
                    result.request_errors[symbol] = f"{registration.name}: {exc}"
                    if complete_fallback:
                        result.fallback_reasons.setdefault(symbol, []).append(f"{registration.name}: {exc}")
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
                    if complete_fallback:
                        result.fallback_reasons.setdefault(symbol, []).append(f"{registration.name}: {exc}")
                    next_pending.append(symbol)
                    continue
                if bars:
                    result.data[symbol] = bars
                    result.providers_used[symbol] = registration.name
                    if complete_fallback and not failure:
                        # A fresh full-window response replaces a failed primary, not a partial-page merge.
                        result.request_errors.pop(symbol, None)
                        if result.fallback_reasons.get(symbol):
                            result.fallback_symbols.append(symbol)
                else:
                    reason = provider_result.failed_symbols.get(symbol)
                    if reason:
                        errors[symbol].append(f"{registration.name}: {reason}")
                    next_pending.append(symbol)
                if complete_fallback and not bars:
                    reason = failure or "empty_response"
                    result.fallback_reasons.setdefault(symbol, []).append(f"{registration.name}: {reason}")
                    logger.warning("provider=%s symbol=%s fallback_reason=%s", registration.name, symbol, reason)
            if complete_fallback:
                logger.info(
                    "provider=%s market=%s symbol_count=%s success_count=%s failed_count=%s "
                    "fallback_pending_count=%s elapsed_seconds=%.3f",
                    registration.name, market.value, len(pending), len(pending) - len(next_pending),
                    len(next_pending), len(next_pending), monotonic() - started,
                )
            pending = next_pending
        for symbol in pending:
            if errors[symbol]:
                result.failed_symbols[symbol] = "; ".join(errors[symbol])
            else:
                result.missing_symbols.append(symbol)
        if complete_fallback:
            result.fallback_symbols.sort()
            logger.info(
                "market=%s fallback_count=%s fallback_symbols=%s",
                market.value, result.fallback_count, result.fallback_symbols,
            )
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
                if market.value in result.failed_symbols:
                    errors.append(f"{registration.name}: {result.failed_symbols[market.value]}")
                    logger.warning("market=%s snapshot failed: %s", market.value, errors[-1])
                    continue
                if result.data:
                    validated = {}
                    for symbol, quote in result.data.items():
                        try:
                            validated[symbol] = validate_quote(quote)
                        except Exception as exc:
                            result.failed_symbols[symbol] = str(exc)
                    result.data = validated
                    if result.data:
                        if errors:
                            logger.info("market=%s snapshot fallback provider=%s", market.value, registration.name)
                        return result
                errors.append(f"{registration.name}: empty snapshot")
                logger.warning("market=%s snapshot failed: %s", market.value, errors[-1])
            except Exception as exc:
                errors.append(f"{registration.name}: {exc}")
                logger.warning("market=%s snapshot failed: %s", market.value, errors[-1])
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
