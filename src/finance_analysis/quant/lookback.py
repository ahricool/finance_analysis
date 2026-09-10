"""Trading-session lookback for daily Alpha158 prediction datasets."""

from __future__ import annotations

from datetime import date, timedelta

from finance_analysis.market_review.trading_calendar import get_trading_days_between  # pragma: allowlist secret
from finance_analysis.quant.markets import get_quant_market_config  # pragma: allowlist secret

# Qlib Alpha158DL rolling windows default to [5, 10, 20, 30, 60]. ROC/Ref on the
# 60-session window is the longest explicit time dependency in this project's
# Alpha158 feature set.
ALPHA158_MAX_ROLLING_WINDOW_SESSIONS = 60
PREDICTION_FEATURE_LOOKBACK_BUFFER_SESSIONS = 20
PREDICTION_FEATURE_LOOKBACK_SESSIONS = (
    ALPHA158_MAX_ROLLING_WINDOW_SESSIONS + PREDICTION_FEATURE_LOOKBACK_BUFFER_SESSIONS
)


def prediction_dataset_start(market: str, trade_date: date) -> date:
    """Oldest date in an inclusive window of prediction feature sessions."""
    calendar_market = get_quant_market_config(market).calendar_market
    sessions = PREDICTION_FEATURE_LOOKBACK_SESSIONS
    pad_days = sessions * 3 + 14
    start_guess = trade_date - timedelta(days=pad_days)
    days = get_trading_days_between(calendar_market, start_guess, trade_date)
    usable = [item for item in days if item <= trade_date]
    if trade_date not in usable:
        usable.append(trade_date)
        usable.sort()
    if len(usable) >= sessions:
        return usable[-sessions]
    return usable[0] if usable else start_guess


__all__ = [
    "ALPHA158_MAX_ROLLING_WINDOW_SESSIONS",
    "PREDICTION_FEATURE_LOOKBACK_BUFFER_SESSIONS",
    "PREDICTION_FEATURE_LOOKBACK_SESSIONS",
    "prediction_dataset_start",
]
