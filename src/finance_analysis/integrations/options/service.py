"""Capability fallback through MarketDataService; Redis caches entire source observations."""

import hashlib
import os

from finance_analysis.core.time import utc_now
from finance_analysis.market_review.trading_calendar import get_effective_trading_date, get_market_now, is_market_open
from .models import OptionChain
from .providers import AlpacaOptionsProvider, YahooOptionsProvider, occ


class OptionsDataService:
    def __init__(self, yahoo=None, alpaca=None, cache=None, config=None):
        from finance_analysis.options_intelligence.config import get_options_config

        self.config = config or get_options_config()
        self.yahoo, self.alpaca = yahoo or YahooOptionsProvider(), alpaca or AlpacaOptionsProvider()
        self.cache = cache
        if cache is None:
            try:
                import redis

                self.cache = redis.Redis.from_url(
                    os.getenv("REDIS_URL", "redis://localhost:6379/0"), socket_connect_timeout=1, socket_timeout=1
                )
            except (ValueError, ImportError):
                pass

    def fetch(self, symbol, now=None):
        now = now or utc_now()
        local = get_market_now("us", now)
        from finance_analysis.market_review.trading_calendar import get_market_session_bounds

        opened = get_market_session_bounds("us", local.date())[0] if is_market_open("us", local.date()) else None
        session_date = local.date() if opened and now >= opened else get_effective_trading_date("us", now)
        config_hash = hashlib.sha256(repr(self.config).encode()).hexdigest()[:12]
        key = f"options:v1:{symbol}:{session_date}:{config_hash}"
        if self.cache is not None:
            try:
                cached = self.cache.get(key)
                if cached:
                    return OptionChain.model_validate_json(cached)
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
        if needs_fallback:
            try:
                spot = next((row.underlying_price for row in result.observations if row.underlying_price), None)
                fallback = self.alpaca.fetch(symbol, now, session_date, self.config, underlying_price=spot)
                # Preserve all rows; primary preference is applied per metric, never by merging fields.
                spot = next((row.underlying_price for row in result.observations if row.underlying_price), None)
                spot_time = next(
                    (row.underlying_timestamp for row in result.observations if row.underlying_timestamp), None
                )
                for row in fallback.observations:
                    row.underlying_price, row.underlying_timestamp = spot, spot_time
                    row.limitations.append("underlying_price_from_yfinance" if spot else "underlying_price_missing")
                result.observations.extend(fallback.observations)
                result.errors.extend(fallback.errors)
                result.coverage["alpaca"] = fallback.coverage
            except Exception as exc:
                # AlpacaHTTPError only contains sanitized classifications.
                from finance_analysis.integrations.market_data.providers.alpaca import AlpacaHTTPError

                reason = str(exc) if isinstance(exc, AlpacaHTTPError) else type(exc).__name__
                result.errors.append(f"alpaca:{reason}")
        # Exclude known adjusted deliverables. Unknown multiplier can support quotes, not premium.
        result.observations = [
            row
            for row in result.observations
            if 0 < (row.expiration - session_date).days <= self.config.max_dte
            and row.strike > 0
            and row.multiplier in {None, 100}
            and not any(c.isdigit() for c in occ(row.symbol)[0])
            and (
                row.underlying_price is None
                or self.config.min_moneyness <= row.strike / row.underlying_price <= self.config.max_moneyness
            )
        ]
        for row in result.observations:
            if row.multiplier is None:
                row.limitations.append("multiplier_unverified_premium_unavailable")
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
