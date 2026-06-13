# -*- coding: utf-8 -*-
"""Intraday market data access with a Longbridge-first, yfinance fallback."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from data_provider.longbridge_fetcher import LongbridgeFetcher
from data_provider.realtime_types import UnifiedRealtimeQuote, safe_float
from data_provider.yfinance_fetcher import YfinanceFetcher

from .bars import normalize_bars

logger = logging.getLogger(__name__)


class IntradayDataSource:
    """Fetches normalized 1-minute bars and realtime quotes for US symbols."""

    def __init__(
        self,
        longbridge_fetcher: Optional[LongbridgeFetcher] = None,
        yfinance_fetcher: Optional[YfinanceFetcher] = None,
    ) -> None:
        self.longbridge = longbridge_fetcher or LongbridgeFetcher()
        self.yfinance = yfinance_fetcher or YfinanceFetcher()

    @staticmethod
    def normalize_us_symbol(code: str) -> str:
        symbol = (code or "").strip().upper()
        if symbol.endswith(".US"):
            return symbol[:-3]
        return symbol

    def fetch_1m_bars(self, symbol: str) -> List[Dict[str, Any]]:
        bars = normalize_bars(self.longbridge.get_minute_candlesticks(symbol, interval=1, count=520))
        if bars:
            return bars
        logger.info("Longbridge 1m K线为空，使用 yfinance 兜底: %s", symbol)
        return self._fetch_yfinance_1m_bars(symbol)

    def fetch_quote(self, symbol: str) -> Optional[UnifiedRealtimeQuote]:
        quote = self.longbridge.get_realtime_quote(symbol)
        if quote is not None:
            return quote
        return self.yfinance.get_realtime_quote(symbol)

    @staticmethod
    def _fetch_yfinance_1m_bars(symbol: str) -> List[Dict[str, Any]]:
        try:
            import yfinance as yf

            hist = yf.Ticker(symbol).history(period="1d", interval="1m", prepost=False, auto_adjust=False)
            if hist.empty:
                return []
            raw_bars: List[Dict[str, Any]] = []
            for ts, row in hist.iterrows():
                close = safe_float(row.get("Close"))
                volume = int(row.get("Volume") or 0)
                turnover = close * volume if close is not None and volume > 0 else None
                raw_bars.append(
                    {
                        "timestamp": ts.isoformat(),
                        "open": safe_float(row.get("Open")),
                        "high": safe_float(row.get("High")),
                        "low": safe_float(row.get("Low")),
                        "close": close,
                        "volume": volume,
                        "turnover": turnover,
                    }
                )
            return normalize_bars(raw_bars)
        except Exception as exc:
            logger.info("yfinance 1m K线兜底失败 %s: %s", symbol, exc)
            return []
