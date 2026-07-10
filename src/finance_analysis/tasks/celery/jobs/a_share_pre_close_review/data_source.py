"""A-share-only market data facade for the pre-close review.

This module deliberately does not instantiate ``DataFetcherManager`` because
that manager may include Longbridge when credentials are configured. The task
uses only the existing efinance and AkShare SDK adapters.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from finance_analysis.integrations.market_data.codes import normalize_stock_code
from finance_analysis.integrations.market_data.providers.akshare import AkshareFetcher
from finance_analysis.integrations.market_data.providers.efinance import EfinanceFetcher

from ..a_share_intraday_analysis.bars import normalize_bars

logger = logging.getLogger(__name__)

ALLOWED_DATA_SOURCES = ("efinance", "akshare")


class ASharePreCloseDataSource:
    """Bounded A-share data access with explicit source order."""

    def __init__(
        self,
        *,
        efinance_fetcher: Optional[EfinanceFetcher] = None,
        akshare_fetcher: Optional[AkshareFetcher] = None,
    ) -> None:
        self.efinance = efinance_fetcher or EfinanceFetcher()
        self.akshare = akshare_fetcher or AkshareFetcher()
        self.sources_used: list[str] = []

    def get_market_snapshot_rows(self) -> list[dict[str, Any]]:
        """Force a provider refresh so a normal short-TTL cache cannot leak in."""
        try:
            rows = self.efinance.get_all_realtime_quotes(force_refresh=True)
            if rows:
                self._record_source("efinance")
                return rows
        except Exception as exc:
            logger.warning("A股收盘前全市场快照获取失败: %s", exc, exc_info=True)
        return []

    def get_main_indices(self) -> list[dict[str, Any]]:
        for name, fetcher in (("efinance", self.efinance), ("akshare", self.akshare)):
            try:
                rows = fetcher.get_main_indices("cn") or []
                if rows:
                    self._record_source(name)
                    return list(rows)
            except Exception as exc:
                logger.warning("%s 获取 A 股指数失败: %s", name, exc)
        return []

    def get_sector_rankings(self, n: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        for name, fetcher in (("efinance", self.efinance), ("akshare", self.akshare)):
            try:
                result = fetcher.get_sector_rankings(n)
                if result and (result[0] or result[1]):
                    self._record_source(name)
                    return list(result[0] or []), list(result[1] or [])
            except Exception as exc:
                logger.warning("%s 获取 A 股板块排行失败: %s", name, exc)
        return [], []

    def get_daily_history(self, code: str, *, days: int) -> tuple[pd.DataFrame, str]:
        normalized = normalize_stock_code(code)
        for name, fetcher in (("efinance", self.efinance), ("akshare", self.akshare)):
            try:
                frame = fetcher.get_daily_data(normalized, days=days)
                if frame is not None and not frame.empty:
                    self._record_source(name)
                    return frame, name
            except Exception as exc:
                logger.info("%s 获取 %s 日线失败: %s", name, normalized, exc)
        return pd.DataFrame(), ""

    def get_minute_bars(
        self,
        code: str,
        *,
        count: int,
        now: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        try:
            raw = self.efinance.get_minute_candlesticks(
                normalize_stock_code(code),
                interval=1,
                count=count,
            )
            bars = normalize_bars(raw, now=now)
            if bars:
                self._record_source("efinance")
            return bars
        except Exception as exc:
            logger.info("efinance 获取 %s 分钟K线失败: %s", code, exc)
            return []

    def get_belonging_boards(self, code: str) -> list[str]:
        try:
            raw = self.efinance.get_belong_board(normalize_stock_code(code))
        except Exception as exc:
            logger.info("efinance 获取 %s 所属板块失败: %s", code, exc)
            return []
        if raw is None or getattr(raw, "empty", True):
            return []
        self._record_source("efinance")
        name_column = next(
            (column for column in ("板块名称", "板块", "名称", "name") if column in raw.columns),
            None,
        )
        if name_column is None:
            return []
        values = [str(value).strip() for value in raw[name_column].tolist() if str(value).strip()]
        return list(dict.fromkeys(values))

    def _record_source(self, name: str) -> None:
        if name not in self.sources_used:
            self.sources_used.append(name)


__all__ = ["ALLOWED_DATA_SOURCES", "ASharePreCloseDataSource"]
