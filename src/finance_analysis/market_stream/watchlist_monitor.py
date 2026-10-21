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
    return symbol.endswith((".SH", ".SZ", ".BJ"))


def load_watchlist_targets(
    repo: Any | None = None,
    portfolio_repo: Any | None = None,
) -> dict[str, SubscriptionTarget]:
    """Load all users' watch-list entries."""
    if repo is None:
        from finance_analysis.database.repositories.watch_list import WatchListRepo

        repo = WatchListRepo()
        if portfolio_repo is None:
            from finance_analysis.database.repositories.portfolio import PortfolioRepository

            portfolio_repo = PortfolioRepository(repo.db)

    targets: dict[str, SubscriptionTarget] = {}
    watch_items = list(repo.list_all()) if repo is not None else []
    entries = [(getattr(item, "code", ""), getattr(item, "market_type", None)) for item in watch_items]
    if portfolio_repo is not None:
        entries.extend(portfolio_repo.monitored_symbols())
    for code, raw_market in entries:
        code = str(code or "").strip()
        try:
            market_type = normalize_market_type(raw_market, code)
            if market_type == "CN":
                from finance_analysis.stocks.markets import canonical_watch_list_code

                symbol = canonical_watch_list_code(code, market_type)
            else:
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
        added = {symbol: target for symbol, target in targets.items() if self.last_targets.get(symbol) != target}
        removed = {symbol: target for symbol, target in self.last_targets.items() if targets.get(symbol) != target}
        self.last_targets = targets
        if added or removed:
            logger.info("WatchList 变化: added=%s removed=%s", sorted(added), sorted(removed))
        return WatchListSnapshot(targets=targets, added=added, removed=removed)
