"""Authenticated snapshot APIs for the Trend Following dashboard."""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder

from finance_analysis.database.models.user import User
from finance_analysis.database.repositories.trend_following import TrendFollowingRepository
from finance_analysis.interfaces.api.deps import require_admin, require_current_user
from finance_analysis.interfaces.api.v1.schemas.trend_following import TrendFollowingRunRequest
from finance_analysis.tasks.celery.schedule import (
    JOB_TREND_FOLLOWING_CN,
    JOB_TREND_FOLLOWING_US,
    QUEUE_ANALYSIS,
    require_scheduled_task_definition,
)
from finance_analysis.trend_following.config import DEFAULT_CONFIG
from finance_analysis.trend_following.universe import universe_by_code

router = APIRouter()
logger = logging.getLogger(__name__)
Market = Literal["CN", "US"]
SortField = Literal["alpha_score", "trend_score", "rs_score", "breakout_score", "rank"]


def _resolve_date(repository: TrendFollowingRepository, requested: date | None) -> date:
    resolved = requested or repository.latest_trade_date()
    if resolved is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trend Following snapshot is not available")
    return resolved


@router.get("/ranking")
async def ranking(
    trade_date: date | None = None,
    sort_by: SortField = "alpha_score",
    limit: int | None = Query(default=None, ge=1, le=1000),
    _: User = Depends(require_current_user),
    market: Market = "CN",
):
    repository = TrendFollowingRepository(market)
    resolved = _resolve_date(repository, trade_date)
    rows = repository.snapshots_by_date(resolved, sort_by=sort_by, limit=limit)
    summary = repository.summary_by_date(resolved)
    if not rows or summary is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Trend Following snapshot not found for {resolved}")
    return jsonable_encoder({**summary, "items": rows})


@router.get("/candidates")
async def candidates(
    trade_date: date | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _: User = Depends(require_current_user),
    market: Market = "CN",
):
    repository = TrendFollowingRepository(market)
    resolved = _resolve_date(repository, trade_date)
    return jsonable_encoder({
        "market": market,
        "trade_date": resolved,
        "summary": repository.summary_by_date(resolved),
        "items": repository.candidates_by_date(resolved, limit=limit),
    })


@router.get("/dates")
async def dates(_: User = Depends(require_current_user), market: Market = "CN"):
    items = TrendFollowingRepository(market).available_trade_dates()
    return jsonable_encoder({"market": market, "latest": items[0] if items else None, "items": items})


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
async def run_trend_following(body: TrendFollowingRunRequest, user: User = Depends(require_admin)):
    from finance_analysis.tasks.celery.jobs.trend_following.tasks import (
        run_trend_following_cn,
        run_trend_following_us,
    )

    job_id = JOB_TREND_FOLLOWING_CN if body.market == "CN" else JOB_TREND_FOLLOWING_US
    task = run_trend_following_cn if body.market == "CN" else run_trend_following_us
    definition = require_scheduled_task_definition(job_id)
    try:
        result = task.apply_async(
            kwargs={
                "trade_date": body.trade_date.isoformat() if body.trade_date else None,
                "scheduler_job_id": definition.job_id,
                "_trigger_source": "manual",
                "_triggered_by_uid": user.id,
            },
            queue=QUEUE_ANALYSIS,
            expires=definition.expires,
        )
    except Exception as exc:
        logger.exception("Failed to submit Trend Following task")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Failed to submit Trend Following task") from exc
    return {"task_id": result.id, "status": "pending", "market": body.market, "trade_date": body.trade_date}


@router.get("/{code}")
async def detail(
    code: str,
    limit: int = Query(default=DEFAULT_CONFIG.history_limit_default, ge=1, le=DEFAULT_CONFIG.history_limit_max),
    trade_date: date | None = None,
    _: User = Depends(require_current_user),
    market: Market = "CN",
):
    canonical = str(code).strip().upper()
    member = universe_by_code(market).get(canonical)
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stock is not in the Trend Following universe")
    repository = TrendFollowingRepository(market)
    resolved = _resolve_date(repository, trade_date)
    history = repository.snapshot_history(canonical, limit=limit, as_of=resolved)
    if not history:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trend Following snapshot is not available")
    metadata = {**member.to_dict(), "name": history[0].get("name") or member.name}
    return jsonable_encoder({
        "market": market,
        "trade_date": resolved,
        "metadata": metadata,
        "latest": history[0],
        "history": history,
        "market_context": repository.summary_by_date(resolved),
    })


__all__ = ["router"]
