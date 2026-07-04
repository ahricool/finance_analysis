"""Database-only historical OHLCV loader used by analysis and Agent tools."""

from __future__ import annotations

import contextvars
from datetime import date, datetime, time
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

from finance_analysis.analysis.history.errors import HistoricalMarketDataMissingError
from finance_analysis.market_review.trading_calendar import MARKET_TIMEZONE, get_completed_trading_days

_frozen_target_date: contextvars.ContextVar[Optional[date]] = contextvars.ContextVar(
    "_frozen_target_date", default=None
)


def set_frozen_target_date(d: date) -> contextvars.Token:
    return _frozen_target_date.set(d)


def get_frozen_target_date() -> Optional[date]:
    return _frozen_target_date.get()


def reset_frozen_target_date(token: contextvars.Token) -> None:
    _frozen_target_date.reset(token)


def market_from_canonical_code(code: str) -> str:
    canonical = str(code or "").strip().upper()
    if canonical.endswith(".US"):
        return "US"
    if canonical.endswith(".HK") and canonical[:-3].isdigit() and not canonical.startswith("0"):
        return "HK"
    if canonical.endswith((".SH", ".SZ")):
        return "CN"
    raise ValueError(f"Canonical ticker.region code required for historical data: {code!r}")


def calculate_daily_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    """Calculate legacy analysis features in memory from complete raw history."""
    result = frame.sort_values("date").reset_index(drop=True).copy()
    close = pd.to_numeric(result["close"], errors="coerce")
    volume = pd.to_numeric(result["volume"], errors="coerce")
    result["pct_chg"] = close.pct_change().mul(100)
    result["ma5"] = close.rolling(5, min_periods=1).mean()
    result["ma10"] = close.rolling(10, min_periods=1).mean()
    result["ma20"] = close.rolling(20, min_periods=1).mean()
    result["volume_ratio"] = volume / volume.rolling(5, min_periods=1).mean().shift(1)
    return result


def load_history_df(
    stock_code: str,
    days: int = 60,
    target_date: Optional[date] = None,
) -> Tuple[pd.DataFrame, str]:
    """Read a complete trading-day window from PostgreSQL or raise explicitly."""
    from finance_analysis.database import get_db
    from finance_analysis.database.repositories.stock import StockRepository

    code = str(stock_code or "").strip().upper()
    market = market_from_canonical_code(code)
    calendar_market = market.lower()
    end = target_date or get_frozen_target_date() or date.today()
    market_tz = ZoneInfo(MARKET_TIMEZONE[calendar_market])
    as_of = datetime.combine(end, time(23, 59), tzinfo=market_tz)
    required_days = get_completed_trading_days(calendar_market, max(1, int(days)), as_of)
    required_start, required_end = required_days[0], required_days[-1]
    repository = StockRepository(get_db())
    bars = repository.get_range(code, required_start, required_end)
    actual_dates = {bar.date for bar in bars}
    missing = [session for session in required_days if session not in actual_dates]
    latest = max(actual_dates) if actual_dates else None
    if missing:
        raise HistoricalMarketDataMissingError(
            market=market,
            code=code,
            interval="1d",
            required_start=required_start,
            required_end=required_end,
            latest_available=latest,
            missing_dates=tuple(missing[:20]),
            missing_count=len(missing),
        )
    frame = pd.DataFrame([bar.to_dict() for bar in bars])
    return calculate_daily_indicators(frame), "database"


__all__ = [
    "calculate_daily_indicators",
    "get_frozen_target_date",
    "load_history_df",
    "market_from_canonical_code",
    "reset_frozen_target_date",
    "set_frozen_target_date",
]
