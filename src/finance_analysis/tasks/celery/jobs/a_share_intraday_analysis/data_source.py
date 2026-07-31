# -*- coding: utf-8 -*-
"""A-share intraday access through the shared market-data service."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from finance_analysis.integrations.market_data import MarketDataService
from finance_analysis.integrations.market_data.codes import normalize_stock_code

from .bars import normalize_bars
from .config import A_SHARE_INDICES, MIN_BARS_FOR_BENCHMARK, MIN_BARS_FOR_SYMBOL

logger = logging.getLogger(__name__)


class AShareIntradayDataSource:
    """Thin facade over the shared fetchers for the intraday task."""

    def __init__(
        self,
        *,
        market_data_service: Optional[MarketDataService] = None,
        realtime_source: Any = None,
    ) -> None:
        self.data_manager = market_data_service or MarketDataService(streaming_source=realtime_source)

    def get_market_snapshot_rows(self) -> List[Dict[str, Any]]:
        """Return the normalized full-market realtime snapshot (one call)."""
        try:
            return [quote.to_dict() for quote in self.data_manager.get_market_snapshot("CN").data.values()]
        except Exception as exc:
            logger.warning("获取 A 股全市场快照失败: %s", exc, exc_info=True)
            return []

    def get_main_indices(self) -> List[Dict[str, Any]]:
        try:
            return [item.to_dict() for item in self.data_manager.get_market_indices("CN")]
        except Exception as exc:
            logger.warning("获取 A 股主要指数失败: %s", exc, exc_info=True)
            return []

    def get_market_stats(self) -> Dict[str, Any]:
        try:
            result = self.data_manager.get_market_stats("CN")
            return result.to_dict() if result else {}
        except Exception as exc:
            logger.warning("获取 A 股市场统计失败: %s", exc, exc_info=True)
            return {}

    def get_sector_rankings(self, n: int = 5) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        try:
            result = self.data_manager.get_sector_rankings("CN", limit=n)
            return (result.top, result.bottom) if result else ([], [])
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
            end = now or datetime.now(timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            result = self.data_manager.get_minute_bars(
                [code], end - timedelta(minutes=max(count * interval, 1)), end, interval=f"{interval}m"
            )
            symbol = next(iter(result.data), None)
            raw = [
                {"timestamp": bar.bar_time.isoformat(), "open": bar.open, "high": bar.high,
                 "low": bar.low, "close": bar.close, "volume": bar.volume, "turnover": bar.amount}
                for bar in (result.data.get(symbol, []) if symbol else [])
            ]
        except Exception as exc:
            logger.info("获取 %s 分钟K线失败: %s", code, exc)
            return []
        bars = normalize_bars(raw, now=now)
        if bars:
            logger.info("symbol=%s source=efinance fallback_reason=longbridge_empty bars=%s", code, len(bars))
        return bars

    def get_quote(self, code: str):
        try:
            result = self.data_manager.get_realtime_quotes([code])
            return next(iter(result.data.values()), None)
        except Exception as exc:
            logger.info("获取 %s 实时行情失败: %s", code, exc)
            return None

    @staticmethod
    def _should_try_longbridge_for_symbol(code: str) -> bool:
        """Longbridge is useful for known symbols, not task benchmark index codes."""
        normalized = normalize_stock_code(str(code or ""))
        return bool(normalized and normalized not in A_SHARE_INDICES)
