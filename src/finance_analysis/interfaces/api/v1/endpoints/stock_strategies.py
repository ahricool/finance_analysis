"""Authenticated shared research reads; only administrators can request evaluation."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from finance_analysis.interfaces.api.deps import require_admin, require_current_user
from finance_analysis.interfaces.api.v1.schemas.stock_strategies import (
    Detail,
    Market,
    Overview,
    RunRequest,
    RunResponse,
)
from finance_analysis.stock_strategies.registry import STRATEGIES
from finance_analysis.stock_strategies.service import StockStrategyService

router = APIRouter()


def get_service():
    return StockStrategyService()


@router.get("", response_model=Overview)
def overview(market: Market = "CN", user=Depends(require_current_user), service=Depends(get_service)):
    return service.overview(market)


@router.post("/run", status_code=202, response_model=RunResponse)
def run(body: RunRequest, user=Depends(require_admin)):
    if body.strategy_key and not any(
        s.key == body.strategy_key and (not body.market or body.market in s.markets) for s in STRATEGIES
    ):
        raise HTTPException(422, "未知策略或策略不支持所选市场")
    from finance_analysis.tasks.celery.jobs.stock_strategies.tasks import DEFINITION, run_stock_strategies

    try:
        result = run_stock_strategies.apply_async(
            kwargs=dict(
                market=body.market, strategy_key=body.strategy_key, _trigger_source="manual", _triggered_by_uid=user.id
            ),
            queue=DEFINITION.queue,
            expires=DEFINITION.expires,
        )
    except Exception as exc:
        raise HTTPException(503, "提交策略任务失败") from exc
    return {"task_id": result.id}


@router.get("/{strategy_key}", response_model=Detail)
def detail(
    strategy_key: str,
    market: Market = "CN",
    before: date | None = None,
    limit: int = Query(100, ge=1, le=200),
    user=Depends(require_current_user),
    service=Depends(get_service),
):
    result = service.detail(strategy_key, market, before, limit)
    if result is None:
        raise HTTPException(404, "未知策略或策略不支持所选市场")
    return result
