"""Today's ordered MA5 pullback/reclaim on fixed, price-aligned prior-session averages."""

from datetime import timedelta
from math import isfinite

from finance_analysis.market_review import trading_calendar
from . import config as c


def pullback_metrics(quote, bars, history, session):
    result = dict(
        pullback_ma5=None,
        pullback_ma10=None,
        pullback_ma_order=None,
        pullback_touch_time=None,
        pullback_reclaim_time=None,
        pullback_holds_ma10=None,
        pullback_gentle=None,
        pullback_reclaimed=None,
        pullback_ready=None,
        pullback_unavailable_reason=None,
    )
    if not trading_calendar._XCALS_AVAILABLE:
        result["pullback_unavailable_reason"] = "交易日历不可用，回踩路线不可评估"
        return result
    expected = trading_calendar.get_trading_days_between(
        session.market.lower(), session.previous_date - timedelta(days=40), session.previous_date
    )[-10:]
    prior = [b for b in history if b.trade_date <= session.previous_date][-10:]
    closes = [getattr(b, "close", None) for b in prior]
    if (
        len(expected) != 10
        or [b.trade_date for b in prior] != expected
        or any(v is None or not isfinite(v) or v <= 0 for v in closes)
        or quote is None
        or quote.pre_close is None
        or not isfinite(quote.pre_close)
        or quote.pre_close <= 0
        or quote.low is None
        or not isfinite(quote.low)
        or quote.low <= 0
    ):
        result["pullback_unavailable_reason"] = "缺少截至昨日连续10个交易日收盘价、可靠昨收或日内最低价，回踩路线不可评估"
        return result
    # Daily bars are forward-adjusted; minutes/quotes are raw. Reuse Trend's actual
    # previous-close anchor to place both fixed averages on today's quote scale.
    factor = quote.pre_close / closes[-1]
    ma5 = sum(closes[-5:]) / 5 * factor
    ma10 = sum(closes) / 10 * factor
    result.update(pullback_ma5=ma5, pullback_ma10=ma10, pullback_ma_order=ma5 >= ma10)
    if not bars:
        return result
    floor = min(quote.low, min(b.low for b in bars))
    holds = floor >= ma10 and quote.price >= ma10
    gentle = floor >= ma5 * (1 - c.PULLBACK_MA_BAND)
    # Require an approach from above; merely opening below MA5 then rebounding is
    # not a pullback. The touch must precede both reclaim closes.
    approached = False
    touched = None
    for bar in bars:
        if touched is None and (approached or bar.open > ma5) and bar.low <= ma5 * (1 + c.PULLBACK_MA_BAND):
            touched = bar.bar_end
        approached = approached or bar.close > ma5
    tail = bars[-c.BREAK_BARS :]
    reclaimed = bool(
        touched is not None
        and len(tail) == c.BREAK_BARS
        and tail[0].bar_start >= touched
        and all(a.bar_end == b.bar_start for a, b in zip(tail, tail[1:]))
        and all(b.close > ma5 * (1 + c.PULLBACK_RECLAIM_BUFFER) for b in tail)
        and quote.price > ma5 * (1 + c.PULLBACK_RECLAIM_BUFFER)
    )
    result.update(
        pullback_touch_time=touched,
        pullback_reclaim_time=tail[-1].bar_end if reclaimed else None,
        pullback_holds_ma10=holds,
        pullback_gentle=gentle,
        pullback_reclaimed=reclaimed,
        pullback_ready=bool(ma5 >= ma10 and holds and gentle and reclaimed),
    )
    return result
