"""Do not bridge missing CN minutes when calculating confirmed indicators."""

from datetime import timedelta

from finance_analysis.market_stream.config import completed_regular_minutes


def indicator_tail(bars, market):
    if market != "CN" and not any(bar.sampled for bar in bars):
        return bars
    tail = []
    previous = None
    for bar in bars:
        position = completed_regular_minutes(bar.bar_time + timedelta(minutes=1), market)
        if bar.partial or (previous is not None and position != previous + 1):
            tail = []
        if not bar.partial:
            tail.append(bar)
        previous = position
    return tail
