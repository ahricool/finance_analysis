# -*- coding: utf-8 -*-
"""Intraday market data access with a Longbridge-first, yfinance fallback."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional

from finance_analysis.integrations.market_data.providers.longbridge.market import LongbridgeFetcher
from finance_analysis.integrations.market_data.realtime_state.data_source import get_default_sync_realtime_source
from finance_analysis.integrations.market_data.realtime_types import UnifiedRealtimeQuote, safe_float
from finance_analysis.integrations.market_data.providers.yfinance import YfinanceFetcher

from .config import DEFAULT_INTRADAY_BAR_COUNT, US_EASTERN
from .bars import normalize_bars
from .market_calendar import parse_timestamp

logger = logging.getLogger(__name__)

_REGULAR_SESSION_START = time(9, 30)
_REGULAR_SESSION_END = time(16, 0)
_MINIMUM_REALTIME_BARS = 15


class IntradayDataSource:
    """Fetches normalized 1-minute bars and realtime quotes for US symbols."""

    def __init__(
        self,
        longbridge_fetcher: Optional[LongbridgeFetcher] = None,
        yfinance_fetcher: Optional[YfinanceFetcher] = None,
        realtime_source: Any = None,
    ) -> None:
        self.longbridge = longbridge_fetcher or LongbridgeFetcher()
        self.yfinance = yfinance_fetcher or YfinanceFetcher()
        self.realtime = realtime_source or get_default_sync_realtime_source()

    @staticmethod
    def normalize_us_symbol(code: str) -> str:
        symbol = (code or "").strip().upper()
        if symbol.endswith(".US"):
            return symbol[:-3]
        return symbol

    def fetch_1m_bars(
        self,
        symbol: str,
        *,
        now: Optional[datetime] = None,
        include_incomplete: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch current US/Eastern trading-day regular-session 1m bars."""
        try:
            realtime_bars = self.realtime.get_recent_bars(
                symbol,
                DEFAULT_INTRADAY_BAR_COUNT,
                market_type="US",
                minimum_count=_MINIMUM_REALTIME_BARS,
                include_incomplete=include_incomplete,
                now=now,
            )
        except Exception as exc:
            realtime_bars = None
            logger.warning("symbol=%s source=market_streamer fallback_reason=redis_error error=%s", symbol, exc)
        if realtime_bars is not None:
            return realtime_bars

        bars = filter_current_trading_day_bars(
            normalize_bars(
                self.longbridge.get_minute_candlesticks(
                    symbol,
                    interval=1,
                    count=DEFAULT_INTRADAY_BAR_COUNT,
                )
            ),
            now=now,
            include_incomplete=include_incomplete,
        )
        if bars:
            logger.info(
                "symbol=%s source=longbridge fallback_reason=%s bars=%s",
                symbol,
                getattr(self.realtime, "fallback_reason", "market_streamer_unavailable"),
                len(bars),
            )
            return bars
        logger.info("symbol=%s source=yfinance fallback_reason=longbridge_empty", symbol)
        return self._fetch_yfinance_1m_bars(symbol, now=now, include_incomplete=include_incomplete)

    def fetch_quote(self, symbol: str) -> Optional[UnifiedRealtimeQuote]:
        try:
            realtime_quote = self.realtime.get_quote(symbol, market_type="US")
        except Exception as exc:
            realtime_quote = None
            logger.warning("symbol=%s source=market_streamer fallback_reason=redis_error error=%s", symbol, exc)
        if realtime_quote is not None:
            return realtime_quote
        quote = self.longbridge.get_realtime_quote(symbol)
        if quote is not None:
            logger.info(
                "symbol=%s source=longbridge fallback_reason=%s",
                symbol,
                getattr(self.realtime, "fallback_reason", "market_streamer_unavailable"),
            )
            return quote
        logger.info("symbol=%s source=yfinance fallback_reason=longbridge_empty", symbol)
        return self.yfinance.get_realtime_quote(symbol)

    @staticmethod
    def _fetch_yfinance_1m_bars(
        symbol: str,
        *,
        now: Optional[datetime] = None,
        include_incomplete: bool = False,
    ) -> List[Dict[str, Any]]:
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
            return filter_current_trading_day_bars(
                normalize_bars(raw_bars),
                now=now,
                include_incomplete=include_incomplete,
            )
        except Exception as exc:
            logger.info("yfinance 1m K线兜底失败 %s: %s", symbol, exc)
            return []


def filter_current_trading_day_bars(
    bars: List[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    include_incomplete: bool = False,
) -> List[Dict[str, Any]]:
    """Keep only current Eastern trading-date regular-session 1m bars.

    The provider may return bars spanning multiple dates or the still-forming
    current minute. This function normalizes timestamps to America/New_York,
    filters to 09:30 <= timestamp < 16:00 for ``now``'s Eastern date, and keeps
    ascending order.
    """
    current = _eastern_now(now)
    trading_date = current.date()
    filtered: List[Dict[str, Any]] = []
    for bar in bars:
        ts = parse_timestamp(bar.get("timestamp"))
        if ts is None:
            continue
        ts = ts.astimezone(US_EASTERN)
        if ts.date() != trading_date:
            continue
        if not (_REGULAR_SESSION_START <= ts.time() < _REGULAR_SESSION_END):
            continue
        if not include_incomplete and ts + timedelta(minutes=1) > current:
            continue
        normalized = dict(bar)
        normalized["timestamp"] = ts.isoformat()
        filtered.append(normalized)
    return sorted(filtered, key=lambda item: item["timestamp"])


def _eastern_now(now: Optional[datetime] = None) -> datetime:
    current = now or datetime.now(US_EASTERN)
    if current.tzinfo is None:
        current = current.replace(tzinfo=US_EASTERN)
    return current.astimezone(US_EASTERN)
