"""Market-data synchronization scopes and benchmark dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from finance_analysis.database.repositories.universe import UniverseResolver


@dataclass(frozen=True)
class MarketScope:
    """Separate equity sync targets from calculation-only market dependencies."""

    market: str
    universe_codes: frozenset[str]
    benchmark_dependency_codes: frozenset[str]
    strategy_dependency_codes: frozenset[str]

    @property
    def synchronization_codes(self) -> frozenset[str]:
        return self.universe_codes | self.benchmark_dependency_codes | self.strategy_dependency_codes


MARKET_BENCHMARK_DEPENDENCIES: dict[str, dict[str, str]] = {
    "US": {
        "QQQ.US": "Invesco QQQ Trust",
        "SPY.US": "SPDR S&P 500 ETF Trust",
        "SOXX.US": "iShares Semiconductor ETF",
        "XLB.US": "Materials Select Sector SPDR Fund",
        "XLC.US": "Communication Services Select Sector SPDR Fund",
        "XLE.US": "Energy Select Sector SPDR Fund",
        "XLF.US": "Financial Select Sector SPDR Fund",
        "XLI.US": "Industrial Select Sector SPDR Fund",
        "XLK.US": "Technology Select Sector SPDR Fund",
        "XLP.US": "Consumer Staples Select Sector SPDR Fund",
        "XLRE.US": "Real Estate Select Sector SPDR Fund",
        "XLU.US": "Utilities Select Sector SPDR Fund",
        "XLV.US": "Health Care Select Sector SPDR Fund",
        "XLY.US": "Consumer Discretionary Select Sector SPDR Fund",
    },
    "CN": {
        # These are the same liquid ETF proxies used by the existing A-share
        # pre-close review. Generic stock-history APIs do not confuse them with
        # same-numbered index codes.
        "510300.SH": "沪深300ETF",
        "510500.SH": "中证500ETF",
        "159915.SZ": "创业板ETF",
    },
}


class MarketDataScopeResolver:
    """Resolve the canonical US/CN daily synchronization scope.

    Strategy membership is resolved from PostgreSQL universes.
    """

    def __init__(self, universe_resolver=None):
        self.universe_resolver = universe_resolver or UniverseResolver()

    def resolve(self, market: str) -> MarketScope:
        normalized_market = str(market or "").strip().upper()
        if normalized_market not in {"US", "CN"}:
            raise ValueError(f"Unsupported market={market}; expected US or CN")
        universe_codes = {
            item.code for item in self.universe_resolver.resolve_universe(f"{normalized_market.lower()}_quant")
        }
        strategy_codes = self.strategy_dependency_codes(normalized_market)
        return MarketScope(
            market=normalized_market,
            universe_codes=frozenset(universe_codes),
            benchmark_dependency_codes=frozenset(MARKET_BENCHMARK_DEPENDENCIES[normalized_market]),
            strategy_dependency_codes=frozenset(strategy_codes),
        )

    def strategy_dependency_codes(self, market: str) -> set[str]:
        normalized_market = str(market).strip().upper()
        if normalized_market not in {"CN", "US"}:
            return set()
        keys = (f"{normalized_market.lower()}_trend", f"{normalized_market.lower()}_etf_rotation")
        return {item.code for key in keys for item in self.universe_resolver.resolve_universe(key)}

    @staticmethod
    def dependency_records(market: str, codes: Iterable[str] | None = None) -> list[dict[str, Any]]:
        normalized_market = str(market).upper()
        dependencies = MARKET_BENCHMARK_DEPENDENCIES[normalized_market]
        selected = set(codes or dependencies)
        return [
            {
                "market": normalized_market,
                "code": code,
                "name": dependencies[code],
                "instrument_type": "ETF",
                "source": "SEED",
            }
            for code in sorted(selected)
            if code in dependencies
        ]

__all__ = [
    "MARKET_BENCHMARK_DEPENDENCIES",
    "MarketDataScopeResolver",
    "MarketScope",
]
