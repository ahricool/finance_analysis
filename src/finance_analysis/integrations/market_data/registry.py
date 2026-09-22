"""Explicit provider capability registration."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping


DRAGON_TIGER_BOARD = "dragon_tiger_board"
LIMIT_UP_POOL = "limit_up_pool"
LIMIT_DOWN_POOL = "limit_down_pool"
LIMIT_BREAK_POOL = "limit_break_pool"
LIMIT_UP_LADDER = "limit_up_ladder"

INDUSTRY_CATALOG = "industry_catalog"
INDEX_QUOTES = "index_quotes"
INDEX_HISTORY = "index_history"
INDEX_CONSTITUENTS = "index_constituents"

DAILY_BARS = "daily_bars"
MINUTE_BARS = "minute_bars"
REALTIME_QUOTES = "realtime_quotes"
LATEST_MARKET_SNAPSHOT = "latest_market_snapshot"
MARKET_INDICES = "market_indices"
MARKET_STATS = "market_stats"
SECTOR_RANKINGS = "sector_rankings"
INSTRUMENT_INFO = "instrument_info"

CAPABILITY_METHODS: Mapping[str, str] = MappingProxyType(
    {
        DRAGON_TIGER_BOARD: "get_dragon_tiger_board",
        LIMIT_UP_POOL: "get_limit_up_pool",
        LIMIT_DOWN_POOL: "get_limit_down_pool",
        LIMIT_BREAK_POOL: "get_limit_break_pool",
        LIMIT_UP_LADDER: "get_limit_up_ladder",
        INDUSTRY_CATALOG: "get_industry_catalog",
        INDEX_QUOTES: "get_index_quotes",
        INDEX_HISTORY: "get_index_history",
        INDEX_CONSTITUENTS: "get_index_constituents",
        DAILY_BARS: "fetch_daily_bars",
        MINUTE_BARS: "fetch_minute_bars",
        REALTIME_QUOTES: "fetch_quotes",
        LATEST_MARKET_SNAPSHOT: "fetch_market_snapshot",
        MARKET_INDICES: "get_indices",
        MARKET_STATS: "get_market_stats",
        SECTOR_RANKINGS: "get_sector_rankings",
        INSTRUMENT_INFO: "get_instrument_info",
    }
)


class ProviderConfigurationError(ValueError):
    """Raised before I/O when a provider selection is invalid."""


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    name: str
    provider: Any
    capabilities: frozenset[str]


class ProviderRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, ProviderRegistration] = {}
        self._internal_names: set[str] = set()

    def register(self, name: str, provider: Any, *, capabilities: Iterable[str]) -> None:
        normalized_name = str(name).strip().lower()
        if not normalized_name:
            raise ProviderConfigurationError("provider name must not be empty")
        normalized_capabilities = frozenset(str(item).strip().lower() for item in capabilities)
        unknown = normalized_capabilities.difference(CAPABILITY_METHODS)
        if unknown:
            raise ProviderConfigurationError(f"provider {normalized_name!r} has unknown capabilities: {sorted(unknown)}")
        for capability in normalized_capabilities:
            method = getattr(provider, CAPABILITY_METHODS[capability], None)
            if not callable(method):
                raise ProviderConfigurationError(
                    f"provider {normalized_name!r} registered {capability!r} but does not implement "
                    f"{CAPABILITY_METHODS[capability]}()"
                )
        if normalized_name in self._registrations:
            raise ProviderConfigurationError(f"provider {normalized_name!r} is already registered")
        self._registrations[normalized_name] = ProviderRegistration(
            normalized_name, provider, normalized_capabilities
        )

    def get(self, name: str) -> ProviderRegistration:
        normalized_name = str(name).strip().lower()
        try:
            return self._registrations[normalized_name]
        except KeyError as exc:
            raise ProviderConfigurationError(f"provider {normalized_name!r} is not registered") from exc

    def resolve(self, names: Iterable[str], capability: str) -> tuple[ProviderRegistration, ...]:
        normalized_capability = str(capability).strip().lower()
        if normalized_capability not in CAPABILITY_METHODS:
            raise ProviderConfigurationError(f"unknown capability {capability!r}")
        resolved = tuple(self.get(name) for name in names)
        unsupported = [item.name for item in resolved if normalized_capability not in item.capabilities]
        if unsupported:
            raise ProviderConfigurationError(
                f"providers {unsupported} do not support capability {normalized_capability!r}"
            )
        return resolved

    def register_internal(self, name: str, provider: Any, *, capabilities: Iterable[str]) -> None:
        """Internal DB/Redis readers participate in routing, not external provider inventory."""
        self.register(name, provider, capabilities=capabilities)
        self._internal_names.add(name)

    def names(self, *, include_internal: bool = False) -> tuple[str, ...]:
        return tuple(name for name in self._registrations if include_internal or name not in self._internal_names)

    def capabilities(self, name: str) -> frozenset[str]:
        return self.get(name).capabilities
