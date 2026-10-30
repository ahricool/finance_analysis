"""GET reads persisted evidence and realized returns; administrators enqueue evaluation."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from finance_analysis.interfaces.api.deps import require_admin, require_current_user
from finance_analysis.interfaces.api.v1.schemas.intraday_confirmation import (
    Market,
    State,
    Source,
    Snapshot,
    Confirmation,
    RunRequest,
    AvailableDates,
)
from finance_analysis.intraday_confirmation.service import ConfirmationService

router = APIRouter()


def get_service():
    return ConfirmationService()


@router.get("", response_model=Snapshot)
def snapshot(
    market: Market = "CN",
    state: State | None = None,
    candidate_source: Source | None = None,
    trade_date: date | None = None,
    user=Depends(require_current_user),
    service=Depends(get_service),
):
    return service.read(market, state, candidate_source, trade_date=trade_date)


@router.get("/dates", response_model=AvailableDates)
def dates(market: Market = "CN", user=Depends(require_current_user), service=Depends(get_service)):
    return service.dates(market)


@router.post("/run", status_code=202)
def run(body: RunRequest, user=Depends(require_admin)):
    from finance_analysis.tasks.celery.jobs.intraday_confirmation.tasks import (
        run_intraday_confirmation_cn,
        run_intraday_confirmation_us,
    )
    from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition

    definition = require_scheduled_task_definition(f"intraday_confirmation_{body.market.lower()}")
    task = run_intraday_confirmation_cn if body.market == "CN" else run_intraday_confirmation_us
    try:
        result = task.apply_async(
            kwargs={"_trigger_source": "manual", "_triggered_by_uid": user.id},
            queue=definition.queue,
            expires=definition.expires,
        )
    except Exception as exc:
        raise HTTPException(503, "提交盘中确认任务失败") from exc
    return {"task_id": result.id, "status": "pending"}


@router.get("/{code}", response_model=Confirmation)
def detail(
    code: str,
    market: Market = "CN",
    trade_date: date | None = None,
    user=Depends(require_current_user),
    service=Depends(get_service),
):
    row = next((r for r in service.read(market, trade_date=trade_date)["items"] if r["code"] == code.upper()), None)
    if row is None:
        raise HTTPException(404, "不在所选日期冻结候选池")
    return row


@router.get("/{code}/evaluations")
def evaluations(
    code: str,
    market: Market = "CN",
    trade_date: date | None = None,
    user=Depends(require_current_user),
    service=Depends(get_service),
):
    from zoneinfo import ZoneInfo
    from finance_analysis.core.time import utc_now

    day = trade_date or utc_now().astimezone(ZoneInfo("Asia/Shanghai" if market == "CN" else "America/New_York")).date()
    return {"items": service.evaluations(market, day, code.upper())}
