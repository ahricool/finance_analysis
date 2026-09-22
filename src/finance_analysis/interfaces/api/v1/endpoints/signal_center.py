"""GETs only read saved evidence, including historical analysis."""

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from finance_analysis.database.repositories.signal_center import SignalCenterRepository
from finance_analysis.interfaces.api.deps import require_current_user
from finance_analysis.interfaces.api.v1.schemas.signal_center import Market, SignalSummary, SignalDetail, DailySignals
from finance_analysis.market_review.trading_calendar import get_market_now

router = APIRouter()


def get_repository():
    return SignalCenterRepository()


@router.get("/daily", response_model=DailySignals)
def daily(signal_date: date | None = None, user=Depends(require_current_user), repo=Depends(get_repository)):
    dates = {m: signal_date or get_market_now(m.lower()).date() for m in ("CN", "US")}
    return dict(requested_dates=dates, items=[r for m, d in dates.items() if (r := repo.get(m, d))])


@router.get("/history", response_model=list[SignalSummary])
def history(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(require_current_user),
    repo=Depends(get_repository),
):
    return repo.history(limit, offset)


@router.get("/{market}/{signal_date}", response_model=SignalDetail)
def detail(market: Market, signal_date: date, user=Depends(require_current_user), repo=Depends(get_repository)):
    result = repo.get(market, signal_date)
    if result is None:
        raise HTTPException(404, "该市场当日没有统一信号记录")
    return result
