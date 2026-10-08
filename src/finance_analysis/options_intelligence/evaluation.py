"""Read-only future outcomes, never written into initial scores or signal evidence."""

from datetime import timedelta
from math import log, sqrt
from statistics import stdev
from finance_analysis.core.time import coerce_aware_utc, utc_now
from finance_analysis.market_review import trading_calendar as calendar


def evaluate(event, bars, now=None):
    now = now or utc_now()
    known = coerce_aware_utc(event["occurred_at"])
    if not calendar._XCALS_AVAILABLE:
        return {"status": "unavailable", "reason": "calendar_unavailable"}
    cal = calendar.xcals.get_calendar("XNYS")
    local_day = calendar.get_market_now("us", known).date()
    first = cal.date_to_session(local_day + timedelta(days=1), direction="next")
    days = []
    for _ in range(21):
        days.append(first)
        first = cal.next_session(first)
    closed = [d.date() for d in days if cal.session_close(d).to_pydatetime() <= now]
    prices = bars.get(event["symbol"], {})
    start = days[0].date()
    base = prices.get(start, {}).get("open")
    result = {
        "method": "next_session_open; exact_session_alignment",
        "entry_date": start.isoformat(),
        "entry_price": base,
        "status": "partial",
        "returns": [],
        "benchmarks": {},
        "max_adverse_5d": None,
        "subsequent_rv_20d": None,
        "rv_change": None,
        "evaluated_at": now.isoformat(),
    }
    for horizon in (1, 3, 5):
        window = [d.date() for d in days[:horizon]]
        target = window[-1]
        ready = target in closed and base and all(prices.get(d, {}).get("close") for d in window)
        result["returns"].append(
            {
                "days": horizon,
                "date": target.isoformat(),
                "value": prices[target]["close"] / base - 1 if ready else None,
                "status": "available" if ready else "pending" if target not in closed else "missing",
            }
        )
        for benchmark in ("SPY.US", "QQQ.US"):
            series = bars.get(benchmark, {})
            anchor = series.get(start, {}).get("open")
            complete = target in closed and anchor and all(series.get(d, {}).get("close") for d in window)
            result["benchmarks"].setdefault(benchmark, []).append(
                {"days": horizon, "value": series[target]["close"] / anchor - 1 if complete else None}
            )
    window = [d.date() for d in days[:5]]
    if base and all(d in closed and prices.get(d, {}).get("low") for d in window):
        result["max_adverse_5d"] = min(0, min(prices[d]["low"] for d in window) / base - 1)
    rv_days = [d.date() for d in days]
    if all(d in closed and prices.get(d, {}).get("close", 0) > 0 for d in rv_days):
        values = [prices[d]["close"] for d in rv_days]
        rv = stdev(log(b / a) for a, b in zip(values, values[1:])) * sqrt(252)
        result["subsequent_rv_20d"] = rv
        initial = event["initial_evidence"].get("rv_20d")
        result["rv_change"] = rv - initial if initial is not None else None
        result["status"] = "complete"
    return result


def with_evaluations(events, market):
    if not events:
        return []
    earliest = min(e["trade_date"] for e in events)
    now = utc_now()
    data = market.get_daily_bars(
        {e["symbol"] for e in events} | {"SPY.US", "QQQ.US"},
        earliest,
        calendar.get_effective_trading_date("us", now),
        adjustment="forward",
        source_policy="db_only",
    )
    bars = {
        symbol: {b.trade_date: {"open": b.open, "close": b.close, "low": b.low} for b in rows}
        for symbol, rows in data.data.items()
    }
    return [{**event, "evaluation": evaluate(event, bars, now)} for event in events]
