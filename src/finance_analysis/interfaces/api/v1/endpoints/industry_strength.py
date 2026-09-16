"""Authenticated shared A-share observations; ranking/history are database-only."""

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from finance_analysis.database.repositories.industry_strength import IndustryStrengthRepository, SORT_FIELDS
from finance_analysis.industry_strength.service import IndustryStrengthService
from finance_analysis.integrations.market_data.providers.fuyao import FuyaoError
from finance_analysis.interfaces.api.deps import require_current_user
from finance_analysis.interfaces.api.v1.schemas.industry_strength import (
    RankingResponse,
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
    return repo.dates()


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


@router.get("/{industry_code}/constituents", response_model=ConstituentsResponse)
def constituents(industry_code: str, repo=Depends(get_repository)):
    if not any(r["industry_code"] == industry_code for r in repo.ranking()):
        raise HTTPException(404, "行业不在最新正式目录中")
    try:
        return IndustryStrengthService(repository=repo).constituents(industry_code)
    except FuyaoError:
        raise HTTPException(503, "扶摇当前成分数据暂不可用，请稍后重试") from None


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
