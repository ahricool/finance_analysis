"""Authenticated shared A-share observations; reads use official DB snapshots or isolated Preview Redis."""

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from finance_analysis.database.repositories.industry_strength import IndustryStrengthRepository, SORT_FIELDS
from finance_analysis.interfaces.api.deps import require_current_user
from finance_analysis.interfaces.api.v1.schemas.industry_strength import (
    RankingResponse,
    StockIndustryContext,
    PreviewResponse,
    DetailResponse,
    HistoryResponse,
    ConstituentsResponse,
)
from finance_analysis.market_review.trading_calendar import get_completed_trading_days

router = APIRouter(dependencies=[Depends(require_current_user)])


def get_repository():
    return IndustryStrengthRepository()


def public(row):
    # Membership evidence is persisted for audit, not repeated in every HTTP history row.
    return {**row, "quality": {k: v for k, v in row["quality"].items() if k != "member_codes"}}


@router.get("/ranking", response_model=RankingResponse)
def ranking(
    trade_date: date | None = None,
    sort_by: str = "strength_rank",
    descending: bool | None = None,
    limit: int = Query(500, ge=1, le=500),
    repo=Depends(get_repository),
):
    if sort_by not in SORT_FIELDS:
        raise HTTPException(422, "Unsupported sort_by")
    rows = repo.ranking(trade_date, sort_by, descending, limit)
    return {
        "trade_date": rows[0]["trade_date"] if rows else trade_date,
        "expected_trade_date": get_completed_trading_days("cn", 1)[-1],
        "items": [public(r) for r in rows],
    }


@router.get("/dates", response_model=list[date])
def dates(repo=Depends(get_repository)):
    return repo.dates(limit=None)


@router.get("/history", response_model=HistoryResponse)
def history(
    trade_date: date | None = None,
    limit: int = Query(20, ge=1, le=60),
    top: int = Query(20, ge=1, le=100),
    repo=Depends(get_repository),
):
    leaders = repo.ranking(trade_date, limit=top)
    if not leaders:
        return {"dates": [], "items": []}
    day = leaders[0]["trade_date"]
    rows = repo.history(day, [r["industry_code"] for r in leaders], limit)
    return {"dates": sorted(repo.dates(day, limit)), "items": [public(r) for r in rows]}


@router.get("/preview", response_model=PreviewResponse)
def preview():
    from finance_analysis.industry_strength.preview import PreviewCache
    from finance_analysis.market_review.trading_calendar import get_market_now

    payload = PreviewCache().read() or {}
    result = payload.get("result")
    if result and result["trade_date"] != get_market_now("cn").date().isoformat():
        payload = {**payload, "result": None}
    return payload


@router.get("/stocks/{code}/context", response_model=list[StockIndustryContext])
def stock_context(code: str, repo=Depends(get_repository)):
    from finance_analysis.integrations.market_data.normalizer import canonical_symbol, infer_market
    try:
        symbol = canonical_symbol(code)
        market = infer_market(symbol).value
    except ValueError as exc:
        raise HTTPException(422, "无效证券代码") from exc
    if market != "CN":
        return []
    return repo.stock_context(symbol)


@router.get("/{industry_code}/constituents", response_model=ConstituentsResponse)
def constituents(industry_code: str, repo=Depends(get_repository)):
    return repo.constituents(industry_code)


@router.get("/{industry_code}", response_model=DetailResponse)
def detail(industry_code: str, trade_date: date | None = None, repo=Depends(get_repository)):
    rows = repo.ranking(trade_date)
    current = next((r for r in rows if r["industry_code"] == industry_code), None)
    if current is None:
        raise HTTPException(404, "该行业在指定交易日暂无正式快照")
    return {
        "current": public(current),
        "history": [public(r) for r in repo.history(current["trade_date"], [industry_code], 20)],
    }
