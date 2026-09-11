"""Read persisted market metrics; computations only run through Celery."""

from datetime import date
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from finance_analysis.interfaces.api.deps import require_current_user, require_admin
from finance_analysis.interfaces.api.v1.schemas.market_structure import (
    MarketStructureResponse,
    MarketStructureRunRequest,
)
from finance_analysis.market_structure.service import read_snapshot

router = APIRouter()


@router.get("", response_model=MarketStructureResponse)
def snapshot(market: Literal["CN", "US"] = "CN", trade_date: date | None = None, user=Depends(require_current_user)):
    result = read_snapshot(market, trade_date)
    if result is None:
        raise HTTPException(404, "暂无市场结构数据")
    return result


@router.post("/run", status_code=202)
def run(body: MarketStructureRunRequest, user=Depends(require_admin)):
    from finance_analysis.tasks.celery.jobs.market_structure.tasks import (
        run_market_structure_cn,
        run_market_structure_us,
    )
    from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition

    definition = require_scheduled_task_definition(f"market_structure_{body.market.lower()}")
    task = run_market_structure_cn if body.market == "CN" else run_market_structure_us
    try:
        result = task.apply_async(
            kwargs={
                **body.model_dump(mode="json", exclude={"market"}),
                "_trigger_source": "manual",
                "_triggered_by_uid": user.id,
            },
            queue=definition.queue,
            expires=definition.expires,
        )
    except Exception as exc:
        raise HTTPException(503, "Failed to submit Market Structure task") from exc
    return {"task_id": result.id, "status": "pending", "market": body.market}
