"""Read-only recap history; missing/stale DB data may be served by providers."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

from finance_analysis.analysis.history.loader import calculate_daily_indicators
from finance_analysis.integrations.market_data import MarketDataService
from finance_analysis.market_review.trading_calendar import get_completed_trading_days


def load_review_history(
    symbol: str, *, target_date: date, days: int = 35, market_data: MarketDataService | None = None
) -> tuple[pd.DataFrame, str]:
    market = market_data if market_data is not None else MarketDataService()
    sessions = get_completed_trading_days(
        "us", max(2, days), datetime.combine(target_date, time.max, tzinfo=ZoneInfo("America/New_York"))
    )
    required = {sessions[-2], target_date}

    result = market.get_daily_bars(
        [symbol], sessions[0], target_date, adjustment="forward", source_policy="db_latest",
        required_dates=required,
    )
    rows = {bar.trade_date: bar for bar in result.data.get(symbol, []) if bar.trade_date in sessions}
    if not required.issubset(rows):
        reason = result.failed_symbols.get(symbol) or result.request_errors.get(symbol) or "missing daily bars"
        missing = ",".join(str(day) for day in sorted(required.difference(rows)))
        raise RuntimeError(f"Recap daily data unavailable: {symbol} missing={missing}; {reason}")
    frame = pd.DataFrame([{**bar.to_dict(), "date": day} for day, bar in sorted(rows.items())])
    return calculate_daily_indicators(frame), result.providers_used.get(symbol, "")
