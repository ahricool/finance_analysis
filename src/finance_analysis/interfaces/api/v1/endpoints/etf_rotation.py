"""Authenticated PostgreSQL-backed API for ETF momentum rotation."""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder

from finance_analysis.database.models.user import User
from finance_analysis.database.repositories.etf_rotation import ETFRotationRepository
from finance_analysis.etf_rotation.config import DEFAULT_CONFIG
from finance_analysis.etf_rotation.universe import enabled_etfs, get_etf_universe, universe_by_code
from finance_analysis.interfaces.api.deps import require_admin, require_current_user
from finance_analysis.interfaces.api.v1.schemas.etf_rotation import ETFRotationRunRequest
from finance_analysis.tasks.celery.schedule import (
    JOB_ETF_ROTATION_CN,
    JOB_ETF_ROTATION_US,
    QUEUE_ANALYSIS,
    require_scheduled_task_definition,
)

router = APIRouter()
logger = logging.getLogger(__name__)
SortField = Literal[
    "composite_score", "entry_score", "momentum_score", "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d",
]
Market = Literal["CN", "US"]


def _metadata_by_code(market: Market) -> dict[str, dict]:
    return {member.code: member.to_dict() for member in get_etf_universe(market)}


def _enrich(rows: list[dict], market: Market) -> list[dict]:
    metadata = _metadata_by_code(market)
    return [{**metadata.get(str(row["code"]), {}), **jsonable_encoder(row)} for row in rows]


def _resolve_date(repository: ETFRotationRepository, requested: date | None) -> date:
    resolved = requested or repository.latest_trade_date()
    if resolved is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ETF Rotation snapshot is not available")
    return resolved


def _market_snapshot(repository: ETFRotationRepository, trade_date: date):
    loader = getattr(repository, "market_snapshot_by_date", None)
    return None if loader is None else loader(trade_date)


def _summary(repository: ETFRotationRepository, market: Market, trade_date: date, rows: list[dict]) -> dict:
    members = enabled_etfs(market)
    codes = {member.code for member in members}
    universe_size = len(members)
    daily_count = len(repository.daily_codes_on_date(codes, trade_date))
    rankable_count = len(rows)
    warnings: list[str] = []
    if daily_count < universe_size:
        warnings.append(f"daily data coverage is partial: {daily_count}/{universe_size}")
    if rankable_count < universe_size:
        warnings.append(f"rankable coverage is partial: {rankable_count}/{universe_size}")
    return {
        "market": market,
        "trade_date": trade_date,
        "universe_size": universe_size,
        "data_ready_count": daily_count,
        "data_coverage": daily_count / universe_size if universe_size else 0,
        "rankable_size": rankable_count,
        "rankable_coverage": rankable_count / universe_size if universe_size else 0,
        "generated_at": max((row["generated_at"] for row in rows), default=None),
        "warnings": warnings,
    }


def _changes(
    repository: ETFRotationRepository,
    market: Market,
    trade_date: date,
    current_rows: list[dict],
) -> dict:
    previous_date_loader = getattr(repository, "previous_trade_date", None)
    previous_date = previous_date_loader(trade_date) if previous_date_loader is not None else None
    previous_rows = (
        repository.snapshots_by_date(previous_date)
        if previous_date is not None
        else []
    )
    previous_by_code = {str(row["code"]): row for row in previous_rows}

    def changed(row: dict) -> dict:
        previous = previous_by_code.get(str(row["code"]), {})
        current_rank = row.get("rank")
        previous_rank = previous.get("rank")
        rank_change = (
            int(previous_rank) - int(current_rank)
            if previous_rank is not None and current_rank is not None
            else row.get("rank_change_1d")
        )
        previous_score = previous.get("composite_score")
        current_score = row.get("composite_score")
        return {
            "current": _enrich([row], market)[0],
            "previous_state": previous.get("state"),
            "previous_action": previous.get("action"),
            "previous_rank": previous_rank,
            "rank_change": rank_change,
            "composite_score_change": (
                float(current_score) - float(previous_score)
                if current_score is not None and previous_score is not None
                else None
            ),
        }

    changes = [changed(row) for row in current_rows]
    current_market = _market_snapshot(repository, trade_date)
    previous_market = _market_snapshot(repository, previous_date) if previous_date is not None else None
    regime_change = None
    if (
        current_market is not None
        and previous_market is not None
        and current_market.get("regime") != previous_market.get("regime")
    ):
        regime_change = {
            "from": previous_market.get("regime"),
            "to": current_market.get("regime"),
        }
    return {
        "previous_trade_date": previous_date,
        "new_buys": [
            item for item in changes
            if item["current"].get("action") == "BUY" and item["previous_action"] != "BUY"
        ],
        "new_exits": [
            item for item in changes
            if item["current"].get("action") == "EXIT" and item["previous_action"] != "EXIT"
        ],
        "new_emerging": [
            item for item in changes
            if item["current"].get("state") == "EMERGING" and item["previous_state"] != "EMERGING"
        ],
        "new_cooling": [
            item for item in changes
            if item["current"].get("state") == "COOLING" and item["previous_state"] != "COOLING"
        ],
        "regime_change": regime_change,
        "rank_movers": sorted(
            [item for item in changes if item["rank_change"] not in {None, 0}],
            key=lambda item: -abs(int(item["rank_change"])),
        )[:10],
    }


@router.get("/ranking")
async def ranking(
    trade_date: date | None = None,
    sort_by: SortField = "composite_score",
    limit: int | None = Query(default=None, ge=1, le=100),
    _: User = Depends(require_current_user),
    market: Market = "CN",
):
    repository = ETFRotationRepository(market)
    resolved = _resolve_date(repository, trade_date)
    all_rows = repository.snapshots_by_date(resolved, sort_by=sort_by)
    if not all_rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"ETF Rotation snapshot not found for {resolved}")
    payload_rows = all_rows if limit is None else all_rows[:limit]
    return {
        **jsonable_encoder(_summary(repository, market, resolved, all_rows)),
        "market_snapshot": jsonable_encoder(_market_snapshot(repository, resolved)),
        "changes": jsonable_encoder(_changes(repository, market, resolved, all_rows)),
        "items": _enrich(payload_rows, market),
    }


@router.get("/candidates")
async def candidates(
    trade_date: date | None = None,
    limit: int = Query(default=DEFAULT_CONFIG.hold_rank_threshold, ge=1, le=40),
    _: User = Depends(require_current_user),
    market: Market = "CN",
):
    repository = ETFRotationRepository(market)
    resolved = _resolve_date(repository, trade_date)
    current = repository.candidates_by_date(resolved, limit=limit)
    exit_loader = getattr(repository, "exits_by_date", None)
    exits = exit_loader(resolved) if exit_loader is not None else []
    return {
        "market": market, "trade_date": resolved,
        "market_snapshot": jsonable_encoder(_market_snapshot(repository, resolved)),
        "candidates": _enrich(current, market),
        "exits": _enrich(exits, market),
        "items": _enrich(current, market),
    }


@router.get("/universe")
async def universe(_: User = Depends(require_current_user), market: Market = "CN"):
    members = get_etf_universe(market)
    return {"market": market, "size": len(members), "items": [member.to_dict() for member in members]}


@router.get("/dates")
async def dates(_: User = Depends(require_current_user), market: Market = "CN"):
    items = ETFRotationRepository(market).available_trade_dates()
    return jsonable_encoder({"market": market, "latest": items[0] if items else None, "items": items})


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
async def run_rotation(body: ETFRotationRunRequest, user: User = Depends(require_admin)):
    from finance_analysis.tasks.celery.jobs.etf_rotation.tasks import run_etf_rotation_cn, run_etf_rotation_us

    job_id = JOB_ETF_ROTATION_CN if body.market == "CN" else JOB_ETF_ROTATION_US
    task = run_etf_rotation_cn if body.market == "CN" else run_etf_rotation_us
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
        logger.exception("Failed to submit ETF Rotation task")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Failed to submit ETF Rotation task") from exc
    return {"task_id": result.id, "status": "pending", "market": body.market, "trade_date": body.trade_date}


# Keep the dynamic code route after every static route above.
@router.get("/{code}")
async def detail(
    code: str,
    limit: int = Query(default=DEFAULT_CONFIG.history_limit_default, ge=1, le=DEFAULT_CONFIG.history_limit_max),
    _: User = Depends(require_current_user),
    market: Market = "CN",
):
    canonical = str(code).strip().upper()
    member = universe_by_code(market).get(canonical)
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ETF is not in the Rotation universe")
    history = ETFRotationRepository(market).snapshot_history(canonical, limit=limit)
    if not history:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ETF Rotation snapshot is not available")
    return {
        "market": market,
        "metadata": member.to_dict(),
        "latest": jsonable_encoder(history[0]),
        "history": jsonable_encoder(history),
        "market_snapshot": jsonable_encoder(_market_snapshot(ETFRotationRepository(market), history[0]["trade_date"])),
    }


__all__ = ["router"]
