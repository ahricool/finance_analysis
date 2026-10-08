"""Capability fallback through MarketDataService; Redis caches entire source observations."""

import hashlib
import os
from collections import defaultdict

from finance_analysis.core.time import utc_now
from finance_analysis.market_review.trading_calendar import get_effective_trading_date, get_market_now, is_market_open
from .models import OptionChain
from .providers import AlpacaOptionsProvider, YahooOptionsProvider, number, timestamp, select_contracts


def quote_reference(quote, now):
    price = number(quote.price) if quote else None
    observed = timestamp(quote.quote_time) if quote else None
    if price and observed and observed <= now:
        return price, observed, quote.provider
    return None


def attach_reference(rows, reference):
    price, observed, source = reference
    for row in rows:
        row.underlying_price, row.underlying_timestamp = price, observed
        row.limitations.append(f"underlying_price_source:{source}")


def limit_chain(chain, session_date, config):
    """Finalize only fetched observations, before persistence; never alter stored snapshots."""
    groups = defaultdict(list)
    for row in chain.observations:
        groups[(row.data_source, row.feed_type)].append(row)
    retained, coverage = [], {}
    for key, rows in groups.items():
        selected, details = select_contracts(rows, session_date, config)
        previous = chain.coverage.get("retained_by_source", {}).get(":".join(key))
        if previous is None:
            previous = chain.coverage if key[0] == "yfinance" else chain.coverage.get(key[0], {})
        # A second boundary filter sees only retained rows. Preserve the original sampling
        # loss instead of reporting that this smaller list was a complete source chain.
        if previous.get("moneyness_filter_applied") == details["moneyness_filter_applied"]:
            details["eligible_contract_count"] = max(
                previous.get("eligible_contract_count", 0), details["eligible_contract_count"]
            )
            details["truncated_contracts"] |= previous.get("truncated_contracts", False)
            for expiry, old in previous.get("expiration_counts", {}).items():
                current = details["expiration_counts"].setdefault(
                    expiry,
                    {
                        "available": old["available"],
                        "retained": {"call": 0, "put": 0},
                    },
                )
                current["available"] = {
                    kind: max(current["available"][kind], old["available"][kind]) for kind in ("call", "put")
                }
            if details["truncated_contracts"] and details["selection_status"] == "complete":
                details["selection_status"] = "limited"
        coverage[":".join(key)] = details
        retained.extend(selected)
        if details["selection_status"] == "underlying_missing_selection_unavailable":
            chain.errors.append("underlying_price_missing_contract_selection_unavailable")
        for row in selected:
            if not number(row.underlying_price):
                row.underlying_price, row.underlying_timestamp = None, None
                row.limitations.append("underlying_price_missing")
            if row.multiplier is None:
                row.limitations.append("multiplier_unverified_premium_unavailable")
    chain.observations = retained
    chain.coverage["retained_by_source"] = coverage
    return chain


class OptionsDataService:
    def __init__(self, yahoo=None, alpaca=None, cache=None, config=None, underlying_quote_loader=None):
        from finance_analysis.options_intelligence.config import get_options_config

        self.config = config or get_options_config()
        self.yahoo, self.alpaca = yahoo or YahooOptionsProvider(), alpaca or AlpacaOptionsProvider()
        # Inject the facade's existing stock-quote method; never construct/call the options facade recursively.
        self.underlying_quote_loader = underlying_quote_loader
        self.cache = cache
        if cache is None:
            try:
                import redis

                self.cache = redis.Redis.from_url(
                    os.getenv("REDIS_URL", "redis://localhost:6379/0"), socket_connect_timeout=1, socket_timeout=1
                )
            except (ValueError, ImportError):
                pass

    def _reference(self, symbol, now):
        if self.underlying_quote_loader is None:
            return None
        try:
            quotes = self.underlying_quote_loader([symbol])
            # A live quote can arrive after the scan's start while providers are fetching.
            return quote_reference(quotes.data.get(symbol), max(now, utc_now()))
        except Exception:
            return None  # An unavailable stock quote must not fabricate a moneyness reference.

    def fetch(self, symbol, now=None):
        now = now or utc_now()
        local = get_market_now("us", now)
        from finance_analysis.market_review.trading_calendar import get_market_session_bounds

        opened = get_market_session_bounds("us", local.date())[0] if is_market_open("us", local.date()) else None
        session_date = local.date() if opened and now >= opened else get_effective_trading_date("us", now)
        config_hash = hashlib.sha256(repr(self.config).encode()).hexdigest()[:12]
        key = f"options:v2:{symbol}:{session_date}:{config_hash}"
        if self.cache is not None:
            try:
                cached = self.cache.get(key)
                if cached:
                    result = OptionChain.model_validate_json(cached)
                    missing = [r for r in result.observations if not number(r.underlying_price)]
                    if missing and (reference := self._reference(symbol, now)):
                        attach_reference(missing, reference)
                    return limit_chain(result, session_date, self.config)
            except Exception:
                pass  # Cache is optional; source errors remain in the response.
        try:
            result = self.yahoo.fetch(symbol, now, session_date, self.config)
        except Exception as exc:
            result = OptionChain(symbol=symbol, observed_at=now, errors=[f"yfinance:{type(exc).__name__}"])
        # Yahoo lacks Greeks, quote timestamps/depth and dated OI: fallback only for these capabilities.
        needs_fallback = not result.observations or not any(
            row.delta is not None and row.quote_timestamp is not None and row.oi_date is not None
            for row in result.observations
        )
        native = next((r for r in result.observations if number(r.underlying_price)), None)
        reference = (
            (native.underlying_price, native.underlying_timestamp, native.data_source)
            if native
            else self._reference(symbol, now)
        )
        if reference:
            attach_reference([r for r in result.observations if not number(r.underlying_price)], reference)
        if needs_fallback:
            try:
                spot = reference[0] if reference else None
                fallback = self.alpaca.fetch(symbol, now, session_date, self.config, underlying_price=spot)
                # Preserve all rows; primary preference is applied per metric, never by merging fields.
                if reference:
                    attach_reference(fallback.observations, reference)
                result.observations.extend(fallback.observations)
                result.errors.extend(fallback.errors)
                result.coverage["alpaca"] = fallback.coverage
            except Exception as exc:
                # AlpacaHTTPError only contains sanitized classifications.
                from finance_analysis.integrations.market_data.providers.alpaca import AlpacaHTTPError

                reason = str(exc) if isinstance(exc, AlpacaHTTPError) else type(exc).__name__
                result.errors.append(f"alpaca:{reason}")
        if reference is None and (reference := self._reference(symbol, now)):
            # The second stock-quote attempt can rescue Yahoo too, even if Alpaca was unavailable.
            attach_reference([r for r in result.observations if not number(r.underlying_price)], reference)
        limit_chain(result, session_date, self.config)
        result.coverage.update(
            {
                "primary": "yfinance",
                "fallback": "alpaca",
                "known_adjusted_contracts_excluded": True,
                "unverified_multiplier_count": sum(r.multiplier is None for r in result.observations),
                "min_moneyness": self.config.min_moneyness,
                "max_moneyness": self.config.max_moneyness,
                "max_dte": self.config.max_dte,
            }
        )
        if self.cache is not None and result.observations:
            try:
                self.cache.setex(key, self.config.cache_seconds, result.model_dump_json())
            except Exception:
                pass
        return result
