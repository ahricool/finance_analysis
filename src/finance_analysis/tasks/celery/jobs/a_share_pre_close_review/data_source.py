"""A-share-only market data facade for the pre-close review."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Sequence

import pandas as pd

from finance_analysis.integrations.market_data.codes import normalize_stock_code  # pragma: allowlist secret
from finance_analysis.integrations.market_data.normalizer import canonical_symbol  # pragma: allowlist secret
from finance_analysis.integrations.market_data import MarketDataService  # pragma: allowlist secret

from .bars import normalize_bars

logger = logging.getLogger(__name__)

ALLOWED_DATA_SOURCES = ("fuyao",)


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
                self._record_source("fuyao")
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

    def get_daily_histories(self, codes: Sequence[str], *, days: int) -> dict[str, tuple[pd.DataFrame, str]]:
        ordered = list(dict.fromkeys(str(code).strip() for code in codes if code))
        if not ordered:
            return {}
        end = date.today()
        result = self.market_data.get_daily_bars(
            ordered,
            end - timedelta(days=max(days * 2, 30)),
            end,
            adjustment="forward",
        )
        loaded: dict[str, tuple[pd.DataFrame, str]] = {}
        for code in ordered:
            bars, provider = self._result_bars(result, code)
            if provider:
                self._record_source(provider)
            entry = (
                pd.DataFrame(
                    [
                        {
                            "date": bar.trade_date,
                            "open": bar.open,
                            "high": bar.high,
                            "low": bar.low,
                            "close": bar.close,
                            "volume": bar.volume,
                            "amount": bar.amount,
                        }
                        for bar in bars[-days:]
                    ]
                )
                if bars
                else pd.DataFrame(),
                provider,
            )
            for key in self._aliases(code):
                loaded[key] = entry
        return loaded

    def get_daily_history(self, code: str, *, days: int) -> tuple[pd.DataFrame, str]:
        histories = self.get_daily_histories([code], days=days)
        return histories.get(code) or histories.get(normalize_stock_code(code), (pd.DataFrame(), ""))

    def get_minute_histories(
        self,
        codes: Sequence[str],
        *,
        count: int,
        now: Optional[datetime] = None,
    ) -> dict[str, list[dict[str, Any]]]:
        ordered = list(dict.fromkeys(str(code).strip() for code in codes if code))
        if not ordered:
            return {}
        try:
            end = now or datetime.now(timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            result = self.market_data.get_minute_bars(ordered, end - timedelta(minutes=count), end, interval="1m")
        except Exception as exc:
            logger.info("fuyao 批量获取分钟K线失败: %s", exc)
            return {key: [] for code in ordered for key in self._aliases(code)}
        loaded: dict[str, list[dict[str, Any]]] = {}
        for code in ordered:
            bars_result, provider = self._result_bars(result, code)
            raw = [
                {
                    "timestamp": bar.bar_time.isoformat(),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "turnover": bar.amount,
                }
                for bar in bars_result
            ]
            bars = normalize_bars(raw, now=now)
            if bars and provider:
                self._record_source(provider)
            for key in self._aliases(code):
                loaded[key] = bars
        return loaded

    def get_minute_bars(
        self,
        code: str,
        *,
        count: int,
        now: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        try:
            histories = self.get_minute_histories([code], count=count, now=now)
            return histories.get(code) or histories.get(normalize_stock_code(code), [])
        except Exception as exc:
            logger.info("fuyao 获取 %s 分钟K线失败: %s", code, exc)
            return []

    @staticmethod
    def _aliases(code: str) -> list[str]:
        keys = [code, normalize_stock_code(code)]
        try:
            keys.append(canonical_symbol(code))
        except (ValueError, TypeError):
            pass
        return list(dict.fromkeys(keys))

    @staticmethod
    def _result_bars(result: Any, code: str) -> tuple[list[Any], str]:
        if code in result.data:
            return result.data.get(code, []), result.providers_used.get(code, "")
        for key in ASharePreCloseDataSource._aliases(code):
            if key in result.data:
                return result.data.get(key, []), result.providers_used.get(key, "")
        if len(result.data) == 1:
            symbol, bars = next(iter(result.data.items()))
            return bars, result.providers_used.get(symbol, "")
        return [], ""

    def _record_source(self, name: str) -> None:
        if name not in self.sources_used:
            self.sources_used.append(name)


__all__ = ["ALLOWED_DATA_SOURCES", "ASharePreCloseDataSource"]
