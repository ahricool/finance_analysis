"""Market-data synchronization scopes and benchmark dependencies."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable

from finance_analysis.database.repositories.watch_list import WatchListRepo
from finance_analysis.stocks.markets import normalize_market_type
from finance_analysis.database.repositories.universe import UniverseResolver

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketScope:
    """Separate equity sync targets from calculation-only market dependencies."""

    market: str
    universe_codes: frozenset[str]
    benchmark_dependency_codes: frozenset[str]
    strategy_dependency_codes: frozenset[str]
    watchlist_records: tuple[dict[str, Any], ...]
    unsupported_symbols: tuple[dict[str, str], ...]

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

    def __init__(self, watchlist_repository: WatchListRepo | None = None, universe_resolver=None):
        self.watchlist_repository = watchlist_repository or WatchListRepo()
        self.universe_resolver = universe_resolver or UniverseResolver()

    def resolve(self, market: str) -> MarketScope:
        normalized_market = str(market or "").strip().upper()
        if normalized_market not in {"US", "CN"}:
            raise ValueError(f"Unsupported market={market}; expected US or CN")
        universe_codes = {
            item.code for item in self.universe_resolver.resolve_universe(f"{normalized_market.lower()}_quant")
        }
        watchlist_records: dict[str, dict[str, Any]] = {}
        unsupported: dict[tuple[str, str], dict[str, str]] = {}
        for item in self.watchlist_repository.list_all():
            try:
                item_market = normalize_market_type(item.market_type, item.code)
                if item_market == "HK":
                    if normalized_market == "CN":
                        code = self.canonical_code(item.code, "HK", allow_hk=True)
                        unsupported[(code, "HK")] = {
                            "code": code,
                            "market": "HK",
                            "reason": "HK daily synchronization is temporarily unsupported",
                        }
                    continue
                if item_market != normalized_market:
                    continue
                code = self.canonical_code(item.code, normalized_market)
            except ValueError as exc:
                logger.warning(
                    "market=%s watchlist_code=%s skipped reason=%s",
                    normalized_market,
                    item.code,
                    exc,
                )
                continue
            universe_codes.add(code)
            watchlist_records[code] = {
                "market": normalized_market,
                "code": code,
                "name": item.name or code,
            }
        strategy_codes = self.strategy_dependency_codes(normalized_market)
        return MarketScope(
            market=normalized_market,
            universe_codes=frozenset(universe_codes),
            benchmark_dependency_codes=frozenset(MARKET_BENCHMARK_DEPENDENCIES[normalized_market]),
            strategy_dependency_codes=frozenset(strategy_codes),
            watchlist_records=tuple(watchlist_records[code] for code in sorted(watchlist_records)),
            unsupported_symbols=tuple(unsupported[key] for key in sorted(unsupported)),
        )

    def strategy_dependency_codes(self, market: str) -> set[str]:
        normalized_market = str(market).strip().upper()
        if normalized_market not in {"CN", "US"}:
            return set()
        keys = (f"{normalized_market.lower()}_trend", f"{normalized_market.lower()}_etf_rotation")
        return {item.code for key in keys for item in self.universe_resolver.resolve_universe(key)}

    def strategy_dependency_records(self, market: str) -> list[dict[str, Any]]:
        normalized_market = str(market).strip().upper()
        if normalized_market not in {"CN", "US"}:
            return []
        keys = (f"{normalized_market.lower()}_trend", f"{normalized_market.lower()}_etf_rotation")
        members_by_code = {
            member.code: member for key in keys for member in self.universe_resolver.resolve_universe(key)
        }
        return [
            {
                "market": normalized_market,
                "code": member.code,
                "name": member.name,
                "instrument_type": member.instrument_type,
                "currency": member.currency,
                "listing_status": member.listing_status,
                "source": member.source,
            }
            for member in members_by_code.values()
        ]

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

    @staticmethod
    def canonical_code(code: str, market: str, *, allow_hk: bool = False) -> str:
        text = str(code or "").strip().upper()
        if market == "US":
            base = text[:-3] if text.endswith(".US") else text
            if not base:
                raise ValueError("empty US ticker")
            return f"{base}.US"
        if market == "HK" and allow_hk:
            base = text.removeprefix("HK")
            if base.endswith(".HK"):
                base = base[:-3]
            if not base.isdigit() or int(base) <= 0:
                raise ValueError("invalid HK ticker")
            return f"{int(base)}.HK"
        base = text.removeprefix("SH").removeprefix("SZ").removeprefix("BJ")
        suffix = ""
        if base.endswith((".SH", ".SS", ".SZ", ".BJ")):
            suffix = base[-3:]
            base = base[:-3]
        if not base.isdigit() or len(base) != 6:
            raise ValueError("invalid CN ticker")
        if suffix in (".SH", ".SS"):
            exchange = ".SH"
        elif suffix == ".SZ":
            exchange = ".SZ"
        elif suffix == ".BJ" or base.startswith(("4", "8")):
            exchange = ".BJ"
        elif base.startswith(("5", "6", "9")):
            exchange = ".SH"
        else:
            exchange = ".SZ"
        return f"{base}{exchange}"


__all__ = [
    "MARKET_BENCHMARK_DEPENDENCIES",
    "MarketDataScopeResolver",
    "MarketScope",
]
