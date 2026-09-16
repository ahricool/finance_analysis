"""Read-only market breadth and important transitions over actual snapshot sessions."""

from collections import Counter
from datetime import date

from finance_analysis.market_review.trading_calendar import get_market_now
from finance_analysis.trend_following.preview_cache import load_preview

STATE_GROUPS = {
    "inactive": ("IDLE", "WATCHING"),
    "emerging": ("CANDIDATE",),
    "healthy": ("TRENDING",),
    "deteriorating": ("WEAKENING", "BROKEN"),
}
VALID_STATES = frozenset(state for group in STATE_GROUPS.values() for state in group)
# Reachable pairs from state.transition_state; smaller priority wins.
# Watching alone is intentionally neutral. BROKEN may form a new candidate,
# while WEAKENING may recover directly to TRENDING.
TRANSITIONS = {
    ("IDLE", "CANDIDATE"): ("strengthening", 1),
    ("WATCHING", "CANDIDATE"): ("strengthening", 1),
    ("BROKEN", "CANDIDATE"): ("strengthening", 1),
    ("CANDIDATE", "TRENDING"): ("strengthening", 0),
    ("WEAKENING", "TRENDING"): ("strengthening", 0),
    ("CANDIDATE", "WEAKENING"): ("deteriorating", 1),
    ("CANDIDATE", "BROKEN"): ("deteriorating", 0),
    ("TRENDING", "WEAKENING"): ("deteriorating", 0),
    ("TRENDING", "BROKEN"): ("deteriorating", 0),
    ("WEAKENING", "BROKEN"): ("deteriorating", 0),
}


def eligible(row: dict) -> bool:
    return type(row.get("rank")) is int and row["rank"] > 0


def aggregate_point(day, counts, denominator, *, is_preview=False):
    valid_count = sum(counts.get(state, 0) for state in VALID_STATES)
    coverage = valid_count / denominator if denominator and denominator > 0 else None
    warning = None
    if denominator is None or denominator <= 0:
        warning = "缺少有效 rankable_count，无法计算占比。"
    elif valid_count != denominator:
        warning = f"State coverage {valid_count}/{denominator}，占比未归一化。"

    def ratio(states):
        return sum(counts.get(state, 0) for state in states) / denominator if coverage is not None else None

    return {
        "trade_date": day, "rankable_count": denominator, "coverage": coverage, "warning": warning,
        "state_counts": {state: counts.get(state, 0) for state in sorted(VALID_STATES)},
        "trend_breadth": ratio(STATE_GROUPS["healthy"]),
        "deterioration_breadth": ratio(STATE_GROUPS["deteriorating"]),
        "participation": ratio((*STATE_GROUPS["emerging"], *STATE_GROUPS["healthy"])),
        **{group: ratio(states) for group, states in STATE_GROUPS.items()}, "is_preview": is_preview,
    }


def _source(market, days, as_of, include_preview):
    from finance_analysis.database.repositories.trend_following import TrendFollowingRepository

    today = get_market_now(market.lower()).date()
    if as_of is not None and as_of > today:
        raise ValueError("as_of must not be later than the market's current date")
    repository = TrendFollowingRepository(market)
    dates = repository.recent_snapshot_dates(as_of=as_of or today, days=days)
    preview, warnings = None, []
    if include_preview and (as_of is None or as_of == today) and today not in dates:
        candidate = load_preview(market)
        if (candidate and candidate.get("status") == "completed" and candidate.get("market") == market
                and candidate.get("trade_date") == today.isoformat() and candidate.get("snapshots")):
            preview = candidate
        else:
            warnings.append("当天暂无可用 Preview。")
    return repository, dates, preview, warnings


def get_breadth_history(market: str, *, days=30, as_of: date | None = None, include_preview=False):
    repository, dates, preview, warnings = _source(market, days, as_of, include_preview)
    counts = {day: Counter() for day in dates}
    summaries = {}
    if dates:
        for row in repository.breadth_counts(dates):
            counts[row["trade_date"]][row["state"]] = row["count"]
        summaries = {row["trade_date"]: row for row in repository.breadth_summaries(dates)}
    points = [aggregate_point(day, counts[day], summaries.get(day, {}).get("rankable_count")) for day in dates]
    if preview:
        points.append(aggregate_point(
            date.fromisoformat(preview["trade_date"]),
            Counter(row.get("state") for row in preview["snapshots"] if eligible(row)),
            preview.get("rankable_count"), is_preview=True,
        ))
    return {
        "market": market, "dates": [point["trade_date"] for point in points], "official_count": len(dates),
        "preview_date": preview["trade_date"] if preview else None,
        "preview_time": preview.get("preview_time") if preview else None,
        "generated_at": max((row["generated_at"] for row in summaries.values()), default=None),
        "points": points, "warnings": warnings,
    }


def get_transitions(market: str, *, days=3, direction="all", limit=20, as_of=None, include_preview=False):
    repository, dates, preview, warnings = _source(market, days + 1, as_of, include_preview)
    by_date = {day: {} for day in dates}
    if dates:
        for row in repository.transition_rows(dates):
            by_date[row["trade_date"]][row["code"]] = row
    preview_date = date.fromisoformat(preview["trade_date"]) if preview else None
    if preview:
        dates = [*dates, preview_date]
        by_date[preview_date] = {row["code"]: row for row in preview["snapshots"] if eligible(row)}
    dates = dates[-(days + 1):]
    official_count = max(0, len([day for day in dates if day != preview_date]) - 1)
    items = []
    for previous_date, current_date in zip(dates, dates[1:]):
        for code, row in by_date[current_date].items():
            previous = by_date[previous_date].get(code)
            classification = TRANSITIONS.get((previous.get("state"), row.get("state"))) if previous else None
            if not classification or direction not in ("all", classification[0]):
                continue
            items.append({
                "code": code, "name": row.get("name") or code,
                "previous_state": previous["state"], "current_state": row["state"],
                "previous_date": previous_date, "trade_date": current_date,
                "previous_rank": previous["rank"], "current_rank": row["rank"],
                "rank_delta": previous["rank"] - row["rank"],
                "alpha_score": row.get("alpha_score"),
                "fragility_score": row.get("fragility_score"),
                "direction": classification[0], "priority": classification[1],
                "is_preview": current_date == preview_date,
            })
    items.sort(key=lambda row: (-row["trade_date"].toordinal(), row["priority"], row["current_rank"], row["code"]))
    return {"market": market, "days": days, "official_count": official_count, "preview_date": preview_date,
            "warnings": warnings, "items": items[:limit]}
