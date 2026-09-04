"""Market-specific quantitative research configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from finance_analysis.database.repositories.universe import UniverseResolver
from finance_analysis.quant.exceptions import UnsupportedUniverseError

DEFAULT_QUANT_UNIVERSES = {"US": "us_quant", "CN": "cn_quant"}


@dataclass(frozen=True)
class QuantMarketConfig:
    market: str
    timezone: str
    market_close_time: time
    market_open_time: time
    default_universe: str
    label_benchmark: str
    primary_benchmark: str
    broad_benchmark: str
    style_benchmark: str

    @property
    def calendar_market(self) -> str:
        return self.market.lower()

    @property
    def regime_benchmarks(self) -> tuple[str, str]:
        return self.primary_benchmark, self.broad_benchmark

    @property
    def benchmark_dependencies(self) -> frozenset[str]:
        return frozenset((self.primary_benchmark, self.broad_benchmark, self.label_benchmark, self.style_benchmark))


QUANT_MARKETS = {
    "US": QuantMarketConfig(
        "US", "America/New_York", time(16), time(9, 30), "us_quant", "SPY.US", "QQQ.US", "SPY.US", "QQQ.US"
    ),
    "CN": QuantMarketConfig(
        "CN", "Asia/Shanghai", time(15), time(9, 30), "cn_quant", "510300.SH", "510300.SH", "510300.SH", "159915.SZ"
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


def get_universe_codes(market: str, resolver: UniverseResolver | None = None) -> set[str]:
    config = get_quant_market_config(market)
    return {item.code for item in (resolver or UniverseResolver()).resolve_universe(config.default_universe)}


def validate_universe_for_market(market: str, universe_key: str | None = None) -> str:
    config = get_quant_market_config(market)
    requested = str(universe_key or config.default_universe).strip()
    if requested != config.default_universe:
        raise UnsupportedUniverseError(
            f"Unsupported universe {requested} for market={config.market}; "
            f"the only supported universe is {config.default_universe}"
        )
    return requested


__all__ = [
    "DEFAULT_QUANT_UNIVERSES",
    "QUANT_MARKETS",
    "QuantMarketConfig",
    "default_universe_for_market",
    "get_universe_codes",
    "get_quant_market_config",
    "validate_universe_for_market",
]
