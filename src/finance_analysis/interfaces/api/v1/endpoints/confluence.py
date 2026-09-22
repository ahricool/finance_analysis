"""Read-only GETs; administrator runs are dispatched to the analysis queue."""

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from finance_analysis.confluence.service import ConfluenceService
from finance_analysis.interfaces.api.deps import require_admin, require_current_user
from finance_analysis.interfaces.api.v1.schemas.confluence import Market, Ranking, Detail, RunRequest

router = APIRouter()


def get_service():
    return ConfluenceService()


@router.get("/ranking", response_model=Ranking)
def ranking(
    market: Market = "CN",
    trade_date: date | None = None,
    min_score: float = Query(0, ge=0, le=100),
    min_signals: int | None = Query(None, ge=1, le=5),
    industry: str | None = None,
    lifecycle: str | None = None,
    early_only: bool = False,
    top_industry: bool = False,
    strong_only: bool = False,
    limit: int = Query(200, ge=1, le=2000),
    user=Depends(require_current_user),
    service=Depends(get_service),
):
    return service.ranking(
        market, trade_date, min_score, min_signals, industry, lifecycle, early_only, top_industry, strong_only, limit
    )


@router.get("/dates", response_model=list[date])
def dates(market: Market = "CN", user=Depends(require_current_user), service=Depends(get_service)):
    return service.repo.dates(market)


@router.post("/run", status_code=202)
def run(body: RunRequest, user=Depends(require_admin)):
    from finance_analysis.tasks.celery.jobs.confluence.tasks import run_confluence_cn, run_confluence_us
    from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition

    definition = require_scheduled_task_definition(f"confluence_{body.market.lower()}")
    task = run_confluence_cn if body.market == "CN" else run_confluence_us
    try:
        result = task.apply_async(
            kwargs={
                "trade_date": body.trade_date.isoformat() if body.trade_date else None,
                "_trigger_source": "manual",
                "_triggered_by_uid": user.id,
            },
            queue=definition.queue,
            expires=definition.expires,
        )
    except Exception as exc:
        raise HTTPException(503, "提交多信号共振任务失败") from exc
    return {"task_id": result.id, "status": "pending", "market": body.market}


@router.get("/{code}", response_model=Detail)
def detail(
    code: str,
    market: Market = "CN",
    trade_date: date | None = None,
    user=Depends(require_current_user),
    service=Depends(get_service),
):
    result = service.repo.read(market, trade_date)
    row = next((r for r in result["items"] if r["code"] == code.upper()), None)
    if row is None:
        raise HTTPException(404, "该股票在所选日期没有共振结果")
    return dict(market=market, trade_date=result["trade_date"], algorithm_version=result["algorithm_version"], item=row)
