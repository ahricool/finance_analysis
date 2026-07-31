# -*- coding: utf-8 -*-
"""US intraday access through the shared market-data service."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from finance_analysis.integrations.market_data import MarketDataService

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
        market_data_service: Optional[MarketDataService] = None,
        realtime_source: Any = None,
    ) -> None:
        self.market_data = market_data_service or MarketDataService(streaming_source=realtime_source)

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
        end = now or datetime.now(timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        result = self.market_data.get_minute_bars(
            [f"{self.normalize_us_symbol(symbol)}.US"],
            end - timedelta(minutes=DEFAULT_INTRADAY_BAR_COUNT),
            end,
            interval="1m",
        )
        values = next(iter(result.data.values()), [])
        bars = [{"timestamp": bar.bar_time.isoformat(), "open": bar.open, "high": bar.high, "low": bar.low,
                 "close": bar.close, "volume": bar.volume, "turnover": bar.amount} for bar in values]
        return filter_current_trading_day_bars(normalize_bars(bars), now=now, include_incomplete=include_incomplete)

    def fetch_quote(self, symbol: str):
        result = self.market_data.get_realtime_quotes([f"{self.normalize_us_symbol(symbol)}.US"])
        return next(iter(result.data.values()), None)


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
