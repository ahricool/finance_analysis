"""Read-only complete history for scheduled analysis, shared within one stock's call."""
from contextvars import ContextVar
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

from finance_analysis.analysis.history.loader import calculate_daily_indicators, market_from_canonical_code
from finance_analysis.market_review.trading_calendar import MARKET_TIMEZONE, get_completed_trading_days

prepared_history = ContextVar("prepared_analysis_history", default=None)


def load_analysis_history(service, code, target_date):
    market = market_from_canonical_code(code).lower()
    cutoff = datetime.combine(target_date, time(23, 59), tzinfo=ZoneInfo(MARKET_TIMEZONE[market]))
    days = get_completed_trading_days(market, 60, cutoff)
    result = service.get_daily_bars(
        [code], days[0], days[-1], adjustment="forward",
        source_policy="db_latest", required_dates=days,
    )
    bars = result.data.get(code, [])
    required = set(days)
    missing = sorted(required - {bar.trade_date for bar in bars})
    if missing:
        raise ValueError(f"{code} 日K数据不足：缺失 {len(missing)} 个交易日，"
                         f"范围 {missing[0]} 至 {missing[-1]}；数据库及 API 未提供完整窗口")
    rows = [dict(bar.to_dict(), date=bar.trade_date, code=code, data_source=bar.provider)
            for bar in bars if bar.trade_date in required]
    return calculate_daily_indicators(pd.DataFrame(rows))


def analysis_context(code, frame):
    today, yesterday = frame.iloc[-1].to_dict(), frame.iloc[-2].to_dict()
    for row in (today, yesterday):
        row["date"] = row["date"].isoformat()
    result = dict(code=code, date=today["date"], today=today, yesterday=yesterday)
    if yesterday["volume"] > 0:
        result["volume_change_ratio"] = round(today["volume"] / yesterday["volume"], 2)
    if yesterday["close"] > 0:
        result["price_change_ratio"] = round((today["close"] / yesterday["close"] - 1) * 100, 2)
    from finance_analysis.database.session import DatabaseManager
    result["ma_status"] = DatabaseManager._analyze_ma_status(
        today["close"], today["ma5"], today["ma10"], today["ma20"],
    )
    return result
