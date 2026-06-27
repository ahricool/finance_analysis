"""Polling adapter for the multi-market PostgreSQL WatchList repository."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from finance_analysis.integrations.market_data.providers.longbridge.market import _to_longbridge_symbol
from finance_analysis.market_stream.symbol_state import SubscriptionTarget
from finance_analysis.stocks.markets import MarketType, normalize_market_type

logger = logging.getLogger(__name__)


def _symbol_matches_market(symbol: str, market_type: MarketType) -> bool:
    if market_type == "US":
        return symbol.endswith(".US")
    if market_type == "HK":
        return symbol.endswith(".HK")
    return symbol.endswith((".SH", ".SZ"))


def load_watchlist_targets(repo: Any | None = None) -> dict[str, SubscriptionTarget]:
    """Load the union of all users' CN/HK/US WatchList entries."""
    if repo is None:
        from finance_analysis.database.repositories.watch_list import WatchListRepo

        repo = WatchListRepo()

    targets: dict[str, SubscriptionTarget] = {}
    for item in repo.list_all():
        code = str(getattr(item, "code", "") or "").strip()
        raw_market = getattr(item, "market_type", None)
        try:
            market_type = normalize_market_type(raw_market, code)
            symbol = _to_longbridge_symbol(code)
            if not symbol or not _symbol_matches_market(symbol, market_type):
                logger.warning("跳过无法转换的 WatchList 标的: code=%r market_type=%r", code, raw_market)
                continue
            targets[symbol] = SubscriptionTarget(symbol=symbol, market_type=market_type)
        except Exception as exc:
            logger.warning(
                "跳过无效 WatchList 标的: code=%r market_type=%r error=%s",
                code,
                raw_market,
                exc,
            )
    return targets


@dataclass(frozen=True, slots=True)
class WatchListSnapshot:
    targets: dict[str, SubscriptionTarget]
    added: dict[str, SubscriptionTarget]
    removed: dict[str, SubscriptionTarget]


class WatchListMonitor:
    def __init__(
        self,
        loader: Callable[[], Mapping[str, SubscriptionTarget]] = load_watchlist_targets,
    ) -> None:
        self.loader = loader
        self.last_targets: dict[str, SubscriptionTarget] = {}

    async def poll(self) -> WatchListSnapshot:
        targets = dict(await asyncio.to_thread(self.loader))
        added = {
            symbol: target
            for symbol, target in targets.items()
            if self.last_targets.get(symbol) != target
        }
        removed = {
            symbol: target
            for symbol, target in self.last_targets.items()
            if targets.get(symbol) != target
        }
        self.last_targets = targets
        if added or removed:
            logger.info("WatchList 变化: added=%s removed=%s", sorted(added), sorted(removed))
        return WatchListSnapshot(targets=targets, added=added, removed=removed)
