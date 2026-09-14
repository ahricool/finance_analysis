"""Bounded, read-only state trajectories anchored to a single persisted ranking."""

from datetime import date

from finance_analysis.market_review.trading_calendar import get_market_now
from finance_analysis.trend_following.preview_cache import load_preview
from finance_analysis.trend_following.read_models import STATE_HISTORY_FIELDS


def _ranked(row: dict) -> bool:
    return type(row.get("rank")) is int and row["rank"] > 0


def get_state_history(
    market: str, *, days: int = 30, limit: int = 50, as_of: date | None = None, include_preview: bool = False,
) -> dict:
    from finance_analysis.database.repositories.trend_following import TrendFollowingRepository

    today = get_market_now(market.lower()).date()
    if as_of is not None and as_of > today:
        raise ValueError("as_of must not be later than the market's current date")
    repository = TrendFollowingRepository(market)
    dates = repository.state_history_dates(as_of=as_of or today, days=days)
    anchor = as_of or (dates[-1] if dates else None)
    preview = None
    warnings = []
    if include_preview and (as_of is None or as_of == today) and today not in dates:
        candidate = load_preview(market)
        if (candidate and candidate.get("status") == "completed" and candidate.get("market") == market
                and candidate.get("trade_date") == today.isoformat() and candidate.get("snapshots")):
            preview = candidate
            anchor = today
        else:
            warnings.append("当天暂无可用 Preview。")
    if preview:
        top = sorted((row for row in preview["snapshots"] if _ranked(row)),
                     key=lambda row: (row["rank"], row["code"]))[:limit]
        codes = [row["code"] for row in top]
    else:
        top = []
        codes = None
    rows = (
        repository.state_history_rows(dates=dates, anchor_date=anchor, limit=limit, codes=codes)
        if anchor is not None and (preview or anchor in dates) else []
    )
    if not preview:
        top = sorted((row for row in rows if row["trade_date"] == anchor and _ranked(row)),
                     key=lambda row: (row["rank"], row["code"]))
        if as_of is not None and as_of not in dates:
            warnings.append("所选日期没有正式 Snapshot，不使用其他日期的 Top 排名替代。")
    by_key = {(row["code"], row["trade_date"]): row for row in rows}
    official_count = len(dates)
    if preview:
        dates = [*dates, today]
        by_key.update({(row["code"], today): row for row in top})
    return {
        "market": market, "anchor_date": anchor, "dates": dates, "official_count": official_count,
        "preview_date": today if preview else None,
        "preview_time": preview.get("preview_time") if preview else None,
        "generated_at": max((row["generated_at"] for row in rows), default=None),
        "warnings": warnings,
        "items": [
            {
                "code": stock["code"], "name": stock.get("name") or stock["code"], "current_rank": stock["rank"],
                "history": [
                    {field: row.get(field) for field in STATE_HISTORY_FIELDS} if row and _ranked(row) else None
                    for day in dates for row in [by_key.get((stock["code"], day))]
                ],
            }
            for stock in top
        ],
    }
