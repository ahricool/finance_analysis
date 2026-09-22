"""DB-only observations; administrator-only asynchronous ingestion."""

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from finance_analysis.database.repositories.dragon_tiger_flow import DragonTigerFlowRepository
from finance_analysis.dragon_tiger_flow.calculator import concept_detail
from finance_analysis.dragon_tiger_flow.calendar import validate_day, sessions_through, expected_date
from finance_analysis.interfaces.api.deps import require_current_user, require_admin
from finance_analysis.interfaces.api.v1.schemas.dragon_tiger_flow import (
    Board,
    Overview,
    DateStatus,
    ConceptDetail,
    StockDetail,
    RunRequest,
    RunResponse,
)

router = APIRouter(dependencies=[Depends(require_current_user)])


def get_repository():
    return DragonTigerFlowRepository()


def observation(
    end_date: date | None = None,
    days: int = Query(1, ge=1, le=20),
    board: Board = "all",
    range_days: int = Query(1, ge=1, le=3),
    repo=Depends(get_repository),
):
    if days not in (1, 5, 10, 20) or range_days not in (1, 3):
        raise HTTPException(422, "窗口只支持1/5/10/20日，榜单周期只支持1/3日")
    if end_date is not None and (end_date > expected_date() or end_date not in sessions_through(end_date, 1)):
        raise HTTPException(422, "截止日期必须为已收盘的A股交易日")
    result = repo.window(end_date, days, board, range_days)
    result["expected_trade_date"] = expected_date().isoformat()
    return result


def check_revision(result, revision):
    if revision is not None and revision != result["revision"]:
        raise HTTPException(409, "数据批次已更新，请重新加载概览")


@router.get("/dates", response_model=list[DateStatus])
def dates(repo=Depends(get_repository)):
    return repo.dates()


@router.get("/overview", response_model=Overview)
def overview(result=Depends(observation)):
    return result


@router.get("/concepts/{concept_id}", response_model=ConceptDetail)
def concept(concept_id: str, revision: str | None = Query(None, max_length=64), result=Depends(observation)):
    check_revision(result, revision)
    detail = concept_detail(result, concept_id)
    if detail is None:
        raise HTTPException(404, "暂无该概念观察")
    return detail


@router.get("/stocks/{symbol}", response_model=StockDetail)
def stock(symbol: str, revision: str | None = Query(None, max_length=64), result=Depends(observation)):
    check_revision(result, revision)
    rows = [r for r in result["evidence"] if r["symbol"] == symbol]
    if not rows:
        raise HTTPException(404, "暂无该股票观察")
    return {
        "revision": result["revision"],
        "rows": rows,
        "hot_money_details": [r for r in result["hot_money_details"] if r["symbol"] == symbol],
    }


@router.post("/run", status_code=202, response_model=RunResponse)
def run(body: RunRequest, user=Depends(require_admin)):
    if body.trade_date:
        try:
            validate_day(body.trade_date)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    from finance_analysis.tasks.celery.jobs.dragon_tiger_flow.tasks import run_dragon_tiger_flow_cn
    from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition

    definition = require_scheduled_task_definition("dragon_tiger_flow_cn")
    payload = body.model_dump(mode="json")
    if body.trade_date is None and body.backfill_days is None:
        # Manual default means latest CLOSED day, including weekends; Beat still skips non-sessions.
        payload["trade_date"] = expected_date().isoformat()
    try:
        task = run_dragon_tiger_flow_cn.apply_async(
            kwargs={**payload, "_trigger_source": "manual", "_triggered_by_uid": user.id},
            queue=definition.queue,
            expires=definition.expires,
        )
    except Exception:
        raise HTTPException(503, "龙虎榜任务提交失败") from None
    return {"task_id": task.id, "status": "pending"}
