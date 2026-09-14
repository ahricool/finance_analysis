"""Read-only rank history assembled from official snapshots and today's preview."""

from datetime import date

from finance_analysis.database.repositories.etf_rotation import ETFRotationRepository
from finance_analysis.etf_rotation.preview_cache import load_preview
from finance_analysis.etf_rotation.universe import get_etf_universe
from finance_analysis.market_review.trading_calendar import get_market_now


def get_rank_history(market: str, *, days: int = 30, as_of: date | None = None, include_preview: bool = True) -> dict:
    today = get_market_now(market.lower()).date()
    cutoff = min(as_of, today) if as_of else today
    members = [member for member in get_etf_universe(market) if member.enabled]
    rows = ETFRotationRepository(market).rank_history(
        [member.code for member in members], days=days, as_of=cutoff,
    )
    dates = sorted({row["trade_date"].isoformat() for row in rows})
    official_count = len(dates)
    ranks = {(row["trade_date"].isoformat(), row["code"]): row["rank"] for row in rows}
    generated_at = max((row["generated_at"] for row in rows if row["generated_at"] is not None), default=None)
    preview_date = None
    preview_time = None
    if include_preview and cutoff == today and today.isoformat() not in dates:
        preview = load_preview(market)
        if (preview and preview.get("status") == "completed" and preview.get("market") == market
                and preview.get("trade_date") == today.isoformat() and preview.get("items")):
            preview_date = today.isoformat()
            preview_time = preview.get("preview_time")
            dates.append(preview_date)
            for row in preview["items"]:
                ranks[(preview_date, row["code"])] = row.get("rank")
    return {
        "market": market, "dates": dates, "official_count": official_count,
        "preview_date": preview_date, "preview_time": preview_time, "generated_at": generated_at,
        "series": [
            {"code": member.code, "name": member.name,
             "ranks": [ranks.get((session, member.code)) for session in dates]}
            for member in members
        ],
    }
