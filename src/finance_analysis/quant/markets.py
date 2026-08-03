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
    label_benchmark: str
    regime_benchmarks: tuple[str, str]

    @property
    def calendar_market(self) -> str:
        return self.market.lower()

    @property
    def primary_benchmark(self) -> str:
        return self.regime_benchmarks[0]

    @property
    def broad_benchmark(self) -> str:
        return self.regime_benchmarks[1]

    @property
    def benchmark_dependencies(self) -> frozenset[str]:
        return frozenset((*self.regime_benchmarks, self.label_benchmark))


QUANT_MARKETS = {
    "US": QuantMarketConfig(
        market="US",
        timezone="America/New_York",
        market_close_time=time(16, 0),
        market_open_time=time(9, 30),
        default_universe=DEFAULT_QUANT_UNIVERSES["US"],
        label_benchmark="SPY.US",
        regime_benchmarks=("QQQ.US", "SPY.US"),
    ),
    "CN": QuantMarketConfig(
        market="CN",
        timezone="Asia/Shanghai",
        market_close_time=time(15, 0),
        market_open_time=time(9, 30),
        default_universe=DEFAULT_QUANT_UNIVERSES["CN"],
        label_benchmark="510300.SH",
        regime_benchmarks=("159915.SZ", "510300.SH"),
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
    config = get_quant_market_config(market)
    normalized_market = config.market
    reference = SP500_STOCK_INDEX if normalized_market == "US" else CSI300_STOCK_INDEX
    codes = {
        MarketDataScopeResolver.canonical_code(code, normalized_market)
        for code in reference
    }
    # The reference lists also carry benchmark ETFs so market-data sync can
    # fetch them.  Benchmarks are model dependencies, not rankable members.
    return codes - set(config.benchmark_dependencies)


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
