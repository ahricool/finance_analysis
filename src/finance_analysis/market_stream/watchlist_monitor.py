"""Polling adapter for the PostgreSQL WatchList repository."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from finance_analysis.integrations.market_data.providers.longbridge.market import _to_longbridge_symbol

logger = logging.getLogger(__name__)


def load_us_watchlist_symbols() -> set[str]:
    from finance_analysis.database.repositories.watch_list import get_watch_list_codes_by_market

    symbols: set[str] = set()
    for code in get_watch_list_codes_by_market("US"):
        symbol = _to_longbridge_symbol(code)
        if symbol and symbol.endswith(".US"):
            symbols.add(symbol)
    return symbols


class WatchListMonitor:
    def __init__(self, loader: Callable[[], set[str]] = load_us_watchlist_symbols) -> None:
        self.loader = loader
        self.last_symbols: set[str] = set()

    async def poll(self) -> tuple[set[str], set[str], set[str]]:
        desired = set(await asyncio.to_thread(self.loader))
        added = desired - self.last_symbols
        removed = self.last_symbols - desired
        self.last_symbols = desired
        if added or removed:
            logger.info("WatchList 变化: added=%s removed=%s", sorted(added), sorted(removed))
        return desired, added, removed
