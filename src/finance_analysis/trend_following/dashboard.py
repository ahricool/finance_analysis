"""Bounded homepage view of official Trend snapshots."""

from datetime import date

from finance_analysis.database.repositories.trend_following import TrendFollowingRepository

HIGHLIGHT_STATES = ("CANDIDATE", "TRENDING", "WEAKENING", "BROKEN")


def dashboard_summary(repository: TrendFollowingRepository, trade_date: date) -> dict | None:
    summary = repository.summary_by_date(trade_date)
    if summary is None:
        return None
    current = repository.dashboard_state_rows(trade_date)
    if not current:
        return None
    previous_date = repository.previous_trade_date(trade_date)
    previous = {
        row["code"]: row.get("state")
        for row in (repository.dashboard_state_rows(previous_date) if previous_date else [])
    }
    counts = dict.fromkeys(HIGHLIGHT_STATES, 0)
    highlights = []
    for row in current:
        state = row.get("state")
        before = previous.get(row["code"])
        if state not in counts or before is None or before == state:
            continue
        counts[state] += 1
        if len(highlights) < 3:
            highlights.append({
                "code": row["code"], "name": row.get("name"),
                "previous_state": before, "current_state": state,
            })
    return {
        "market": repository.market, "trade_date": trade_date,
        "market_regime": summary["market_regime"], "market_score": summary["market_score"],
        "score_breakdown": {
            key: (summary.get("score_breakdown") or {}).get(key)
            for key in ("trend", "breadth", "risk")
        },
        "features": {
            key: (summary.get("features") or {}).get(key)
            for key in ("lifecycle_counts", "high_fragility_count")
        },
        "changes": {"previous_trade_date": previous_date, "state_counts": counts, "highlights": highlights},
    }
