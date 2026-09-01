"""A-share-only market data facade for the pre-close review."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd

from finance_analysis.integrations.market_data.codes import normalize_stock_code
from finance_analysis.integrations.market_data import MarketDataService

from ..a_share_intraday_analysis.bars import normalize_bars

logger = logging.getLogger(__name__)

ALLOWED_DATA_SOURCES = ("efinance", "akshare")


class ASharePreCloseDataSource:
    """Bounded A-share data access with explicit source order."""

    def __init__(
        self,
        *,
        market_data_service: Optional[MarketDataService] = None,
    ) -> None:
        self.market_data = market_data_service or MarketDataService()
        self.sources_used: list[str] = []

    def get_market_snapshot_rows(self) -> list[dict[str, Any]]:
        """Force a provider refresh so a normal short-TTL cache cannot leak in."""
        try:
            rows = [quote.to_dict() for quote in self.market_data.get_market_snapshot("CN").data.values()]
            if rows:
                self._record_source("efinance")
                return rows
        except Exception as exc:
            logger.warning("A股收盘前全市场快照获取失败: %s", exc, exc_info=True)
        return []

    def get_main_indices(self) -> list[dict[str, Any]]:
        rows = self.market_data.get_market_indices("CN", providers=ALLOWED_DATA_SOURCES)
        if rows:
            self._record_source(rows[0].provider)
        return [row.to_dict() for row in rows]

    def get_sector_rankings(self, n: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        result = self.market_data.get_sector_rankings("CN", providers=ALLOWED_DATA_SOURCES, limit=n)
        if result:
            self._record_source(result.provider)
            return result.top, result.bottom
        return [], []

    def get_daily_history(self, code: str, *, days: int) -> tuple[pd.DataFrame, str]:
        normalized = normalize_stock_code(code)
        end = date.today()
        result = self.market_data.get_daily_bars(
            [normalized],
            end - timedelta(days=max(days * 2, 30)),
            end,
            adjustment="forward",
        )
        bars = next(iter(result.data.values()), [])
        if not bars:
            return pd.DataFrame(), ""
        provider = next(iter(result.providers_used.values()))
        self._record_source(provider)
        return pd.DataFrame([{"date": bar.trade_date, "open": bar.open, "high": bar.high, "low": bar.low,
                              "close": bar.close, "volume": bar.volume, "amount": bar.amount}
                             for bar in bars[-days:]]), provider

    def get_minute_bars(
        self,
        code: str,
        *,
        count: int,
        now: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        try:
            end = now or datetime.now(timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            result = self.market_data.get_minute_bars([normalize_stock_code(code)], end - timedelta(minutes=count), end,
                                                      interval="1m", providers=ALLOWED_DATA_SOURCES)
            bars_result = next(iter(result.data.values()), [])
            raw = [{"timestamp": bar.bar_time.isoformat(), "open": bar.open, "high": bar.high, "low": bar.low,
                    "close": bar.close, "volume": bar.volume, "turnover": bar.amount} for bar in bars_result]
            bars = normalize_bars(raw, now=now)
            if bars:
                self._record_source("efinance")
            return bars
        except Exception as exc:
            logger.info("efinance 获取 %s 分钟K线失败: %s", code, exc)
            return []

    def get_belonging_boards(self, code: str) -> list[str]:
        try:
            raw = self.market_data.get_belong_boards(normalize_stock_code(code))
        except Exception as exc:
            logger.info("efinance 获取 %s 所属板块失败: %s", code, exc)
            return []
        if not raw:
            return []
        self._record_source("efinance")
        values = [str(row.get("板块名称") or row.get("板块") or row.get("名称") or row.get("name") or "").strip()
                  for row in raw]
        values = [value for value in values if value]
        return list(dict.fromkeys(values))

    def _record_source(self, name: str) -> None:
        if name not in self.sources_used:
            self.sources_used.append(name)


__all__ = ["ALLOWED_DATA_SOURCES", "ASharePreCloseDataSource"]
