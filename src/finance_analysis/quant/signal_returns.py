"""Request-time realized returns from persisted forward-adjusted daily closes."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from math import isfinite

from finance_analysis.database.repositories.quant import QuantRepository


def _return(latest, base) -> float | None:
    if latest is None or base is None:
        return None
    latest, base = float(latest), float(base)
    if not isfinite(latest) or not isfinite(base) or latest <= 0 or base <= 0:
        return None
    value = latest / base - 1
    return value if isfinite(value) else None


def signal_returns(repo: QuantRepository, codes: set[str], signal_date: date | None) -> dict[str, dict]:
    """Forward returns from the selected snapshot's exact trade_date (T0).

    T3/T5 are the third/fifth stored daily bars after T0, never trailing returns.
    Missing T0 or unobserved future bars stay null; no substitute baseline.
    """
    histories = defaultdict(list)
    if codes and signal_date is not None:
        for row in repo.load_return_daily_rows(codes, signal_date):
            histories[row["code"]].append(row)
    results = {}
    for code in codes:
        rows = histories[code]
        base = next((row["close"] for row in rows if row["date"] == signal_date), None)
        closes = {row["ordinal"]: row["close"] for row in rows}
        latest = next(
            (row for row in rows if row["date"] == row["latest_valid_date"] and row["date"] > signal_date),
            None,
        )
        return_since = _return(latest["close"], base) if latest else None
        results[code] = {
            "return_3d": _return(closes.get(4), base),
            "return_5d": _return(closes.get(6), base),
            "return_since": return_since,
            "return_as_of": latest["date"] if latest and return_since is not None else None,
        }
    return results
