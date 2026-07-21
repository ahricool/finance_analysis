"""Market-specific quantitative research configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from finance_analysis.quant.exceptions import UnsupportedQuantUniverseError
from finance_analysis.stocks.market_scope import MarketDataScopeResolver
from finance_analysis.stocks.reference_data.stock_index import CSI300_STOCK_INDEX, SP500_STOCK_INDEX


DEFAULT_QUANT_UNIVERSES = {
    "US": "us_sp500",
    "CN": "cn_csi300",
}


@dataclass(frozen=True)
class QuantMarketConfig:
    market: str
    timezone: str
    market_close_time: time
    market_open_time: time
    default_universe: str
    primary_benchmark: str
    broad_benchmark: str
    risk_benchmark: str

    @property
    def calendar_market(self) -> str:
        return self.market.lower()

    @property
    def benchmark_dependencies(self) -> frozenset[str]:
        return frozenset((self.primary_benchmark, self.broad_benchmark, self.risk_benchmark))


QUANT_MARKETS = {
    "US": QuantMarketConfig(
        market="US",
        timezone="America/New_York",
        market_close_time=time(16, 0),
        market_open_time=time(9, 30),
        default_universe=DEFAULT_QUANT_UNIVERSES["US"],
        primary_benchmark="QQQ.US",
        broad_benchmark="SPY.US",
        risk_benchmark="SOXX.US",
    ),
    "CN": QuantMarketConfig(
        market="CN",
        timezone="Asia/Shanghai",
        market_close_time=time(15, 0),
        market_open_time=time(9, 30),
        default_universe=DEFAULT_QUANT_UNIVERSES["CN"],
        primary_benchmark="510300.SH",
        broad_benchmark="510500.SH",
        risk_benchmark="159915.SZ",
    ),
}


def get_quant_market_config(market: str) -> QuantMarketConfig:
    normalized = str(market or "").strip().upper()
    try:
        return QUANT_MARKETS[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported quant market={market}; expected US or CN") from exc


def default_universe_for_market(market: str) -> str:
    return get_quant_market_config(market).default_universe


def get_quant_universe_codes(market: str) -> set[str]:
    """Return the canonical codes for the market's single fixed Quant Universe."""
    normalized_market = get_quant_market_config(market).market
    reference = SP500_STOCK_INDEX if normalized_market == "US" else CSI300_STOCK_INDEX
    return {
        MarketDataScopeResolver.canonical_code(code, normalized_market)
        for code in reference
    }


def validate_universe_for_market(market: str, universe_key: str | None = None) -> str:
    """Resolve and validate the single fixed universe for a quant market."""
    config = get_quant_market_config(market)
    expected = config.default_universe
    requested = str(universe_key or expected).strip()
    if requested != expected:
        raise UnsupportedQuantUniverseError(
            f"Unsupported universe {requested} for market={config.market}; "
            f"the only supported universe is {expected}"
        )
    return expected


__all__ = [
    "DEFAULT_QUANT_UNIVERSES",
    "QUANT_MARKETS",
    "QuantMarketConfig",
    "default_universe_for_market",
    "get_quant_universe_codes",
    "get_quant_market_config",
    "validate_universe_for_market",
]
