"""Read frozen private reviews; manual runs may only capture the current pre-close window."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from finance_analysis.database.repositories.holdings_review import HoldingsReviewRepository
from finance_analysis.holdings_review.calendar import default_dates, review_window, next_review_at
from finance_analysis.interfaces.api.deps import get_effective_uid, require_current_user
from finance_analysis.interfaces.api.v1.schemas.holdings_review import ReviewResponse, ReviewDates, ReviewRun

router = APIRouter(dependencies=[Depends(require_current_user)])


def repository():
    return HoldingsReviewRepository()


def private(response):
    response.headers["Cache-Control"] = "private, no-store"


@router.get("", response_model=ReviewResponse)
def detail(
    request: Request,
    response: Response,
    market: str = Query("CN", pattern="^(CN|US)$"),
    trade_date: date | None = None,
    repo=Depends(repository),
):
    private(response)
    uid = get_effective_uid(request)
    today, previous = default_dates(market)
    row = repo.get(uid, market, trade_date or today)
    if trade_date is None and row is None:
        row = repo.get(uid, market, previous)
    current = repo.get(uid, market, today)
    return {
        "review": row,
        "requested_date": (trade_date or today).isoformat(),
        "today": today.isoformat(),
        "previous_trade_date": previous.isoformat(),
        "scheduled_at": next_review_at(market).isoformat(),
        "can_run": review_window(market) is not None
        and not (current or {}).get("status") in {"completed", "processing"},
    }


@router.get("/dates", response_model=ReviewDates)
def dates(
    request: Request, response: Response, market: str = Query("CN", pattern="^(CN|US)$"), repo=Depends(repository)
):
    private(response)
    return {"items": repo.dates(get_effective_uid(request), market)}


@router.post("/run", response_model=ReviewRun)
def run(request: Request, market: str = Query("CN", pattern="^(CN|US)$"), repo=Depends(repository)):
    uid = get_effective_uid(request)
    window = review_window(market)
    if window is None:
        raise HTTPException(409, "只允许在当前交易日收盘前50分钟起的15分钟窗口生成复盘，历史日期仅支持查看")
    current = repo.get(uid, market, window[0].date())
    if current and current["status"] == "completed":
        raise HTTPException(409, "当天复盘已完成，历史结论不覆盖")
    if market == "CN":
        from finance_analysis.tasks.celery.jobs.a_share_pre_close_review.tasks import (
            analysis_a_share_pre_close_review as task,
        )
    else:
        from finance_analysis.tasks.celery.jobs.us_pre_close_review.tasks import analysis_us_pre_close_review as task
    result = task.apply_async(
        kwargs={"uid": uid, "owner_uid": uid, "_trigger_source": "manual", "_triggered_by_uid": uid}, queue="analysis"
    )
    return {"task_id": str(result.id)}
