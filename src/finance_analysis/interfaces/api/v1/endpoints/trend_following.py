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
from finance_analysis.interfaces.api.v1.schemas.trend_following import (
    TrendFollowingPortfolioResponse,
    TrendFollowingRunRequest,
)
from finance_analysis.tasks.celery.schedule import (
    JOB_TREND_FOLLOWING_CN,
    JOB_TREND_FOLLOWING_US,
    QUEUE_ANALYSIS,
    require_scheduled_task_definition,
)
from finance_analysis.trend_following.config import DEFAULT_CONFIG
from finance_analysis.trend_following.risk import theoretical_position_weight
from finance_analysis.trend_following.universe import universe_by_code

router = APIRouter()
logger = logging.getLogger(__name__)
Market = Literal["CN", "US"]
SortField = Literal["alpha_score", "trend_score", "rs_score", "breakout_score", "rank"]


def _changes(
    repository: TrendFollowingRepository,
    trade_date: date,
    current_rows: list[dict],
    current_summary: dict,
) -> dict:
    previous_date_loader = getattr(repository, "previous_trade_date", None)
    previous_date = previous_date_loader(trade_date) if previous_date_loader is not None else None
    previous_rows = (
        repository.snapshots_by_date(previous_date, sort_by="rank", limit=None)
        if previous_date is not None
        else []
    )
    previous_summary = repository.summary_by_date(previous_date) if previous_date is not None else None
    previous_by_code = {str(row["code"]): row for row in previous_rows}

    def changed(row: dict) -> dict:
        previous = previous_by_code.get(str(row["code"]), {})

        def delta(key: str) -> float | None:
            current_value = row.get(key)
            previous_value = previous.get(key)
            return (
                float(current_value) - float(previous_value)
                if current_value is not None and previous_value is not None
                else None
            )

        current_rank = row.get("rank")
        previous_rank = previous.get("rank")
        return {
            "current": row,
            "previous_state": previous.get("state"),
            "previous_action": previous.get("action"),
            "previous_pending_action": previous.get("pending_action"),
            "previous_rank": previous_rank,
            "rank_change": (
                int(previous_rank) - int(current_rank)
                if previous_rank is not None and current_rank is not None
                else None
            ),
            "trend_score_change": delta("trend_score"),
            "rs_score_change": delta("rs_score"),
            "alpha_score_change": delta("alpha_score"),
        }

    changes = [changed(row) for row in current_rows]
    current_breadth = (current_summary.get("score_breakdown") or {}).get("breadth")
    previous_breadth = ((previous_summary or {}).get("score_breakdown") or {}).get("breadth")
    market_score_change = (
        float(current_summary["market_score"]) - float(previous_summary["market_score"])
        if previous_summary is not None
        else None
    )
    breadth_score_change = (
        float(current_breadth) - float(previous_breadth)
        if current_breadth is not None and previous_breadth is not None
        else None
    )
    return {
        "previous_trade_date": previous_date,
        "market_score_change": market_score_change,
        "breadth_score_change": breadth_score_change,
        "new_candidates": [
            item for item in changes
            if item["current"].get("state") == "CANDIDATE" and item["previous_state"] != "CANDIDATE"
        ],
        "new_weakening": [
            item for item in changes
            if item["current"].get("state") == "WEAKENING" and item["previous_state"] != "WEAKENING"
        ],
        "new_reduces": [
            item for item in changes
            if (
                item["current"].get("action") == "REDUCE"
                or item["current"].get("pending_action") == "REDUCE"
            ) and item["previous_action"] != "REDUCE" and item["previous_pending_action"] != "REDUCE"
        ],
        "new_exits": [
            item for item in changes
            if (
                item["current"].get("action") == "EXIT"
                or item["current"].get("pending_action") == "EXIT"
            ) and item["previous_action"] != "EXIT" and item["previous_pending_action"] != "EXIT"
        ],
        "transitions": [
            item for item in changes
            if item["previous_state"] is not None
            and item["previous_state"] != item["current"].get("state")
        ],
        "movers": sorted(
            [
                item for item in changes
                if item["rank_change"] not in {None, 0}
                or abs(item["trend_score_change"] or 0.0) >= 5.0
                or abs(item["rs_score_change"] or 0.0) >= 5.0
            ],
            key=lambda item: -max(
                abs(item["rank_change"] or 0),
                abs(item["trend_score_change"] or 0.0),
                abs(item["rs_score_change"] or 0.0),
            ),
        )[:12],
    }


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
    change_rows = rows
    if limit is not None:
        change_rows = repository.snapshots_by_date(resolved, sort_by="rank", limit=None)
    return jsonable_encoder({**summary, "changes": _changes(repository, resolved, change_rows, summary), "items": rows})


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


@router.get("/portfolio", response_model=TrendFollowingPortfolioResponse)
async def portfolio(
    trade_date: date | None = None,
    _: User = Depends(require_current_user),
    market: Market = "CN",
):
    repository = TrendFollowingRepository(market)
    resolved = _resolve_date(repository, trade_date)
    summary = repository.summary_by_date(resolved)
    if summary is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Trend Following summary not found for {resolved}")
    positions = []
    for row in repository.positions_by_date(resolved):
        unit_weight = float(row.get("suggested_initial_weight") or 0.0)
        max_weight = float(row.get("suggested_max_weight") or 0.0)
        position_weight = theoretical_position_weight(row.get("units"), unit_weight, max_weight)
        positions.append({
            "code": row["code"],
            "name": row.get("name") or row["code"],
            "state": row["state"],
            "action": row["action"],
            "pending_action": row.get("pending_action"),
            "units": int(row["units"]),
            "unit_weight": unit_weight,
            "position_weight": position_weight,
            "max_weight": max_weight,
            "entry_price": row.get("entry_price"),
            "reference_price": row["reference_price"],
            "opened_at": row.get("opened_at"),
            "initial_stop": row.get("initial_stop"),
            "trailing_stop": row.get("trailing_stop"),
            "next_add_price": row.get("next_add_price"),
            "exit_level": row.get("exit_level"),
            "alpha_score": row["alpha_score"],
        })
    max_exposure = float(summary["suggested_max_exposure"])
    current_exposure = sum(item["position_weight"] for item in positions)
    return jsonable_encoder({
        "market": market,
        "trade_date": resolved,
        "market_regime": summary["market_regime"],
        "max_exposure": max_exposure,
        "current_exposure": current_exposure,
        "remaining_exposure": max(0.0, max_exposure - current_exposure),
        "position_count": len(positions),
        "positions": positions,
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
    summary = repository.summary_by_date(resolved)
    if not history or history[0]["trade_date"] != resolved or summary is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Trend Following snapshot not found for {canonical} on {resolved}",
        )
    metadata = {**member.to_dict(), "name": history[0].get("name") or member.name}
    return jsonable_encoder({
        "market": market,
        "trade_date": resolved,
        "metadata": metadata,
        "latest": history[0],
        "history": history,
        "market_context": summary,
    })


__all__ = ["router"]
