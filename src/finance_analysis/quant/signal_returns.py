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
    """3D/5D include the latest bar: last / first close of the N-bar window.

    The signal date is the selected snapshot's trade_date, not first-ever selection.
    Missing/invalid window endpoints stay null; no calendar-day approximation.
    """
    histories = defaultdict(list)
    if codes:
        for row in repo.load_return_daily_rows(codes, signal_date):
            histories[row["code"]].append(row)
    results = {}
    for code in codes:
        rows = sorted(histories[code], key=lambda row: row["date"], reverse=True)
        latest = rows[0]["close"] if rows else None
        recent = {row["recency"]: row["close"] for row in rows}
        base = next((row["close"] for row in rows if row["date"] == row["first_date"]), None)
        results[code] = {
            "return_3d": _return(latest, recent.get(3)),
            "return_5d": _return(latest, recent.get(5)),
            "return_since": _return(latest, base),
            "return_as_of": rows[0]["date"] if rows else None,
        }
    return results
