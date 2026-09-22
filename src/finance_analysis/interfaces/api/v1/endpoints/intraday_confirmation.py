"""GET only reads cached evidence; administrators enqueue evaluation."""

from fastapi import APIRouter, Depends, HTTPException
from finance_analysis.interfaces.api.deps import require_admin, require_current_user
from finance_analysis.interfaces.api.v1.schemas.intraday_confirmation import (
    Market,
    State,
    Source,
    Snapshot,
    Confirmation,
    RunRequest,
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
    user=Depends(require_current_user),
    service=Depends(get_service),
):
    return service.read(market, state, candidate_source)


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
def detail(code: str, market: Market = "CN", user=Depends(require_current_user), service=Depends(get_service)):
    row = next((r for r in service.read(market)["items"] if r["code"] == code.upper()), None)
    if row is None:
        raise HTTPException(404, "不在当天冻结候选池")
    return row
