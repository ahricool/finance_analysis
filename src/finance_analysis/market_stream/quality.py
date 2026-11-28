"""Select a bounded run of adjacent usable minutes for live technical indicators."""
from datetime import timedelta

from finance_analysis.market_stream.config import completed_regular_minutes, is_regular_session_minute, market_trading_date

INDICATOR_WINDOW = 120
MINUTE = timedelta(minutes=1)


def indicator_tail(bars, market):
    tail = []
    previous = None
    for bar in bars[-INDICATOR_WINDOW:]:
        if bar.partial or not bar.is_valid():
            tail.clear()
            previous = None
            continue
        if previous is not None and bar.bar_time - previous != MINUTE:
            # CN/HK's scheduled lunch is adjacent in trading minutes.
            lunch = (market in {"CN", "HK"}
                     and is_regular_session_minute(previous, market)
                     and is_regular_session_minute(bar.bar_time, market)
                     and market_trading_date(previous, market) == market_trading_date(bar.bar_time, market)
                     and completed_regular_minutes(bar.bar_time + MINUTE, market)
                     == completed_regular_minutes(previous + MINUTE, market) + 1)
            if not lunch:
                tail.clear()
        tail.append(bar)
        previous = bar.bar_time
    return tail
