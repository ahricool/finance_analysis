"""Read-only exact-session returns from the immutable first-confirmation quote."""

from copy import deepcopy
from datetime import datetime
from math import isfinite
from zoneinfo import ZoneInfo

from finance_analysis.integrations.market_data.research import following_sessions, valid_bar

HORIZONS = (3, 5, 10)


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value > 0


def with_returns(store, market, day, rows, now):
    result = [deepcopy(row) for row in rows]
    for row in result:
        evidence = row.get("return_evidence", {})
        for n in HORIZONS:
            row[f"return_{n}d"] = evidence.get(str(n), {}).get("value")
    eligible = []
    tz = ZoneInfo("Asia/Shanghai" if market == "CN" else "America/New_York")
    for row in result:
        try:
            confirmed = datetime.fromisoformat(row["first_confirmed_at"])
            quoted = datetime.fromisoformat(row["first_confirmed_quote_time"])
            if (confirmed.tzinfo is None or quoted.tzinfo is None or quoted > confirmed or confirmed > now
                    or confirmed.astimezone(tz).date() != day or quoted.astimezone(tz).date() != day):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        if (positive(row.get("first_confirmed_price")) and positive(row.get("first_confirmation_open"))
                and any(row[f"return_{n}d"] is None for n in HORIZONS)):
            eligible.append(row)
    if not eligible:
        return result
    try:
        plan = following_sessions(market, day, max(HORIZONS))
    except Exception:
        # A missing/unsupported calendar is not permission to guess weekdays.
        return result
    closed = [d for d, close in plan if close <= now]
    if len(closed) < min(HORIZONS):
        return result
    pairs = {(row["code"], d) for row in eligible for d in [day, *closed]}
    bars = {(r["code"], r["date"]): r for r in store.load_evaluation_bars(pairs)}
    for row in eligible:
        base = bars.get((row["code"], day))
        if not valid_bar(base):
            continue
        # One read alone does not prove a shared scale: incremental sync can leave old
        # rows on an earlier adjustment basis. Verify same write generation AND provider
        # below, then persist mature ratios in the task so old rolling windows stay useful.
        adjusted_entry = row["first_confirmed_price"] * base["open"] / row["first_confirmation_open"]
        if not positive(adjusted_entry):
            continue
        for n in HORIZONS:
            if row[f"return_{n}d"] is not None:
                continue
            target, close = plan[n - 1]
            window = [base, *[bars.get((row["code"], d)) for d, _ in plan[:n]]]
            if close > now or any(not valid_bar(bar) for bar in window):
                continue
            source, generation = base.get("data_source"), base.get("updated_at")
            if not source or source == "mixed" or generation is None:
                continue
            if any(bar.get("data_source") != source or bar.get("updated_at") != generation for bar in window):
                continue
            value = bars[(row["code"], target)]["close"] / adjusted_entry - 1
            if isfinite(value):
                row[f"return_{n}d"] = value
                row.setdefault("return_evidence", {})[str(n)] = dict(
                    value=value, target_date=target, evaluated_at=now,
                    adjustment_generation=generation.isoformat(), data_source=source, adjusted_entry=adjusted_entry,
                    inputs=[{k: bar[k] for k in ("date", "open", "high", "low", "close", "volume")} for bar in window],
                )
    return result
