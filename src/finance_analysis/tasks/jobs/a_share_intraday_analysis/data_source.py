# -*- coding: utf-8 -*-
"""A-share intraday market-data access built on existing fetchers.

The full-market snapshot and sector / index context come from the shared
:class:`DataFetcherManager` and :class:`EfinanceFetcher`. Minute bars are fetched
on demand only for the bounded candidate set.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from finance_analysis.integrations.market_data.base import DataFetcherManager
from finance_analysis.integrations.market_data.providers.efinance import EfinanceFetcher
from finance_analysis.integrations.market_data.realtime_types import UnifiedRealtimeQuote

from .bars import normalize_bars

logger = logging.getLogger(__name__)


class AShareIntradayDataSource:
    """Thin facade over the shared fetchers for the intraday task."""

    def __init__(
        self,
        *,
        data_manager: Optional[DataFetcherManager] = None,
        efinance_fetcher: Optional[EfinanceFetcher] = None,
    ) -> None:
        self.data_manager = data_manager or DataFetcherManager()
        self.efinance = efinance_fetcher or EfinanceFetcher()

    def get_market_snapshot_rows(self) -> List[Dict[str, Any]]:
        """Return the normalized full-market realtime snapshot (one call)."""
        try:
            return self.efinance.get_all_realtime_quotes()
        except Exception as exc:
            logger.warning("获取 A 股全市场快照失败: %s", exc, exc_info=True)
            return []

    def get_main_indices(self) -> List[Dict[str, Any]]:
        try:
            return self.data_manager.get_main_indices("cn") or []
        except Exception as exc:
            logger.warning("获取 A 股主要指数失败: %s", exc, exc_info=True)
            return []

    def get_market_stats(self) -> Dict[str, Any]:
        try:
            return self.data_manager.get_market_stats() or {}
        except Exception as exc:
            logger.warning("获取 A 股市场统计失败: %s", exc, exc_info=True)
            return {}

    def get_sector_rankings(self, n: int = 5) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        try:
            top, bottom = self.data_manager.get_sector_rankings(n)
            return top or [], bottom or []
        except Exception as exc:
            logger.warning("获取 A 股板块排行失败: %s", exc, exc_info=True)
            return [], []

    def fetch_minute_bars(
        self,
        code: str,
        *,
        interval: int = 1,
        count: int = 240,
        now: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch and normalize recent minute bars for a single security."""
        try:
            raw = self.efinance.get_minute_candlesticks(code, interval=interval, count=count)
        except Exception as exc:
            logger.info("获取 %s 分钟K线失败: %s", code, exc)
            return []
        return normalize_bars(raw, now=now)

    def get_quote(self, code: str) -> Optional[UnifiedRealtimeQuote]:
        try:
            return self.data_manager.get_realtime_quote(code, log_final_failure=False)
        except Exception as exc:
            logger.info("获取 %s 实时行情失败: %s", code, exc)
            return None
