"""Read-only forward performance, separate from immutable decision evidence."""

from datetime import date, datetime, timedelta
from math import isfinite

from finance_analysis.core.time import utc_now
from finance_analysis.market_review import trading_calendar as calendar

HORIZONS = (1, 3, 5, 10)
METHOD = "next_session_open_v1"


def session_plan(signal):
    """Exact exchange sessions; never guess weekdays when the calendar is unavailable."""
    if not calendar._XCALS_AVAILABLE:
        raise ValueError("calendar_unavailable")
    day = date.fromisoformat(str(signal["signal_date"]))
    completed = signal.get("completed_at")
    completed = datetime.fromisoformat(completed) if isinstance(completed, str) else completed
    if completed is None or completed.tzinfo is None:
        raise ValueError("missing_completion_time")
    market = signal["market"].lower()
    cal = calendar.xcals.get_calendar(calendar.MARKET_EXCHANGE[market])
    local_day = calendar.get_market_now(market, completed).date()
    session = cal.date_to_session(max(day + timedelta(days=1), local_day), direction="next")
    # A delayed retry may finish after the next open. That open was not available to the user.
    if cal.session_open(session).to_pydatetime() <= completed:
        session = cal.next_session(session)
    result = []
    for i in range(10):
        result.append((session.date(), cal.session_close(session).to_pydatetime()))
        if i < 9:
            session = cal.next_session(session)
    return result


def valid_bar(row):
    if row is None:
        return False
    prices = [row.get(k) for k in ("open", "high", "low", "close")]
    if any(v is None or not isfinite(v) or v <= 0 for v in prices):
        return False
    op, high, low, close = prices
    volume = row.get("volume")
    return low <= min(op, close) <= max(op, close) <= high and volume is not None and isfinite(volume) and volume > 0


def empty_evaluation(status, reason=None):
    return dict(
        method=METHOD,
        status=status,
        reason=reason,
        entry_date=None,
        entry_price=None,
        as_of=None,
        observed_sessions=0,
        missing_dates=[],
        horizons=[],
        mfe=None,
        mae=None,
        max_drawdown_close=None,
        evaluated_at=utc_now(),
    )


def calculate(plan, bars, now):
    """Day 1 is entry session's close. Missing sessions are never replaced by later bars."""
    result = empty_evaluation("pending")
    result["entry_date"] = plan[0][0]
    closed = [day for day, close in plan if close <= now]
    available = {day: bars[day] for day in closed if valid_bar(bars.get(day))}
    missing = [day for day in closed if day not in available]
    result.update(observed_sessions=len(available), missing_dates=missing, as_of=max(available, default=None))
    base = available.get(plan[0][0], {}).get("open")
    result["entry_price"] = base
    points = []
    for horizon in HORIZONS:
        day, close = plan[horizon - 1]
        window = [d for d, _ in plan[:horizon]]
        state = "pending" if close > now else "missing" if any(d not in available for d in window) else "available"
        points.append(
            dict(
                days=horizon,
                target_date=day,
                status=state,
                value=available[day]["close"] / base - 1 if state == "available" else None,
            )
        )
    result["horizons"] = points
    if missing:
        result.update(status="unavailable" if base is None else "partial", reason="missing_or_invalid_bars")
    elif closed:
        result["status"] = "complete" if len(closed) == 10 else "partial"
        result["mfe"] = max(0.0, max(r["high"] / base - 1 for r in available.values()))
        result["mae"] = min(0.0, min(r["low"] / base - 1 for r in available.values()))
        peak, drawdown = base, 0.0
        for day in closed:
            close = available[day]["close"]
            peak = max(peak, close)
            drawdown = min(drawdown, close / peak - 1)
        result["max_drawdown_close"] = drawdown
    return result


def with_evaluations(repo, signals, now=None):
    """One batched OHLC read per response, at most ten exact dates per BUY signal."""
    now = now or utc_now()
    results, plans, pairs = [], {}, set()
    for signal in signals:
        row = dict(signal)
        results.append(row)
        if row["status"] != "completed" or row["decision"] != "BUY" or not row["selected_symbol"]:
            row["evaluation"] = empty_evaluation("not_applicable")
            continue
        try:
            plan = session_plan(row)
        except Exception:
            row["evaluation"] = empty_evaluation("unavailable", "calendar_or_completion_unavailable")
            continue
        plans[len(results) - 1] = plan
        pairs.update((row["selected_symbol"], day) for day, close in plan if close <= now)
    bars = {(r["code"], r["date"]): r for r in repo.load_evaluation_bars(pairs)} if pairs else {}
    for index, plan in plans.items():
        row = results[index]
        row["evaluation"] = calculate(plan, {d: bars.get((row["selected_symbol"], d)) for d, _ in plan}, now)
    return results
