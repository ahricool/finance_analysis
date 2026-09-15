"""Authenticated snapshot APIs for the Trend Following dashboard."""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response

from finance_analysis.core.preview_metadata import preview_metadata
from finance_analysis.database.models.user import User  # pragma: allowlist secret
from finance_analysis.database.repositories.trend_following import (  # pragma: allowlist secret
    MEANINGFUL_STATES,
    TrendFollowingRepository,
)
from finance_analysis.interfaces.api.deps import require_admin, require_current_user  # pragma: allowlist secret
from finance_analysis.interfaces.api.v1.schemas.trend_following import (  # pragma: allowlist secret
    TrendFollowingRunRequest,
    TrendBreadthResponse,
    TrendTransitionsResponse,
)
from finance_analysis.tasks.celery.schedule import (  # pragma: allowlist secret
    JOB_TREND_FOLLOWING_CN,
    JOB_TREND_FOLLOWING_US,
    QUEUE_ANALYSIS,
    require_scheduled_task_definition,
)
from finance_analysis.core.ranking import calculate_rank_changes  # pragma: allowlist secret
from finance_analysis.trend_following.ranking_cache import RankingCache
from finance_analysis.trend_following.read_models import CANDIDATE_FIELDS, ranking_item
from finance_analysis.trend_following.config import DEFAULT_CONFIG  # pragma: allowlist secret
from finance_analysis.trend_following.preview_cache import load_preview  # pragma: allowlist secret
from finance_analysis.trend_following.universe import universe_by_code  # pragma: allowlist secret

router = APIRouter()
logger = logging.getLogger(__name__)
Market = Literal["CN", "US"]
SortField = Literal[
    "alpha_score", "trend_score", "rs_score", "breakout_score", "rank", "trend_duration_days", "fragility_score"
]


def _changes(
    repository: TrendFollowingRepository,
    trade_date: date,
    current_rows: list[dict],
    current_summary: dict,
) -> dict:
    previous_date_loader = getattr(repository, "previous_trade_date", None)
    previous_date = previous_date_loader(trade_date) if previous_date_loader is not None else None
    previous_rows = (
        repository.change_rows(previous_date)
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
            "code": row["code"],
            "name": row.get("name"),
            "current_state": row.get("state"),
            "current_rank": current_rank,
            "previous_state": previous.get("state"),
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
            if item.get("current_state") == "CANDIDATE" and item["previous_state"] != "CANDIDATE"
        ],
        "new_weakening": [
            item for item in changes
            if item.get("current_state") == "WEAKENING" and item["previous_state"] != "WEAKENING"
        ],
        "new_broken": [
            item for item in changes
            if item.get("current_state") == "BROKEN" and item["previous_state"] != "BROKEN"
        ],
        "transitions": [
            item for item in changes
            if item["previous_state"] is not None
            and item["previous_state"] != item.get("current_state")
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
def ranking(
    trade_date: date | None = None,
    sort_by: SortField = "alpha_score",
    limit: int | None = Query(default=None, ge=1, le=1000),
    _: User = Depends(require_current_user),
    market: Market = "CN",
):
    started = time.perf_counter()
    repository = TrendFollowingRepository(market)
    resolved = _resolve_date(repository, trade_date)
    cache = RankingCache(market, resolved)
    body = cache.load() if sort_by == "alpha_score" and limit is None else None
    if body is not None:
        logger.info("trend_ranking market=%s date=%s cache=hit seconds=%.3f bytes=%s",
                    market, resolved, time.perf_counter() - started, len(body))
        return Response(body, media_type="application/json")
    rows = repository.dashboard_rows(resolved)
    summary = repository.summary_by_date(resolved)
    if not rows or summary is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Trend Following snapshot not found for {resolved}")
    ordered = sorted(rows, key=lambda row: (
        row.get(sort_by) is None,
        (row.get(sort_by) or 0) * (1 if sort_by == "rank" else -1), row["code"],
    ))
    items = [ranking_item(row) for row in (ordered if limit is None else ordered[:limit])]
    historical = repository.historical_composite_ranks(resolved, [str(row["code"]) for row in items])
    for row in items:
        row.update(calculate_rank_changes(row["rank"], historical.get(str(row["code"]), {})))
    candidate_rows = [row for row in rows if row.get("state") in MEANINGFUL_STATES]
    payload = {
        **summary, "changes": _changes(repository, resolved, rows, summary), "items": items,
        "candidates": [{key: row.get(key) for key in CANDIDATE_FIELDS} for row in candidate_rows[:100]],
    }
    body = json.dumps(jsonable_encoder(payload), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    if (
        sort_by == "alpha_score" and limit is None
        and summary.get("data_coverage", 0) >= DEFAULT_CONFIG.minimum_data_coverage
    ):
        cache.save(body)
    logger.info("trend_ranking market=%s date=%s cache=miss seconds=%.3f bytes=%s items=%s",
                market, resolved, time.perf_counter() - started, len(body), len(items))
    return Response(body, media_type="application/json")


@router.get("/breadth-history", response_model=TrendBreadthResponse)
def breadth_history(
    days: int = Query(default=30, ge=1, le=120),
    as_of: date | None = None,
    include_preview: bool = False,
    _: User = Depends(require_current_user),
    market: Market = "CN",
):
    from finance_analysis.trend_following.breadth import get_breadth_history

    try:
        return get_breadth_history(market, days=days, as_of=as_of, include_preview=include_preview)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/transitions", response_model=TrendTransitionsResponse)
def transitions(
    days: int = Query(default=3, ge=1, le=5),
    direction: Literal["all", "strengthening", "deteriorating"] = "all",
    limit: int = Query(default=20, ge=1, le=20),
    as_of: date | None = None,
    include_preview: bool = False,
    _: User = Depends(require_current_user),
    market: Market = "CN",
):
    from finance_analysis.trend_following.breadth import get_transitions

    if days not in (1, 3, 5):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "days must be 1, 3 or 5")
    try:
        return get_transitions(market, days=days, direction=direction, limit=limit,
                               as_of=as_of, include_preview=include_preview)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/candidates")
def candidates(
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
def dates(_: User = Depends(require_current_user), market: Market = "CN"):
    items = TrendFollowingRepository(market).available_trade_dates()
    return jsonable_encoder({"market": market, "latest": items[0] if items else None, "items": items})


@router.get("/preview/status")
def preview_status(_: User = Depends(require_current_user), market: Market = "CN"):
    payload = load_preview(market)
    if payload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trend Following preview is not available")
    return jsonable_encoder(preview_metadata(payload, rows_key="snapshots"))


@router.get("/preview")
def preview(_: User = Depends(require_current_user), market: Market = "CN"):
    payload = load_preview(market)
    if payload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trend Following preview is not available")
    return jsonable_encoder(payload)


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def run_trend_following(body: TrendFollowingRunRequest, user: User = Depends(require_admin)):
    from finance_analysis.tasks.celery.jobs.trend_following.tasks import (  # pragma: allowlist secret
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
def detail(
    code: str,
    limit: int = Query(default=DEFAULT_CONFIG.history_limit_default, ge=1, le=DEFAULT_CONFIG.history_limit_max),
    trade_date: date | None = None,
    _: User = Depends(require_current_user),
    market: Market = "CN",
    before_trade_date: date | None = None,
):
    """Return exact-date detail, or official history only strictly before before_trade_date."""
    if trade_date is not None and before_trade_date is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "trade_date and before_trade_date are mutually exclusive")
    canonical = str(code).strip().upper()
    member = universe_by_code(market).get(canonical)
    if member is None and trade_date is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stock is not in the Trend Following universe")
    repository = TrendFollowingRepository(market)
    if before_trade_date is not None:
        history = repository.snapshot_history(canonical, limit=limit, before_trade_date=before_trade_date)
        return jsonable_encoder({"history": history})
    resolved = _resolve_date(repository, trade_date)
    history = repository.snapshot_history(canonical, limit=limit, as_of=resolved)
    summary = repository.summary_by_date(resolved)
    if not history or history[0]["trade_date"] != resolved or summary is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Trend Following snapshot not found for {canonical} on {resolved}",
        )
    # Historical heatmap anchors can contain a stock that has since left the universe.
    metadata = {
        **(member.to_dict() if member is not None else {"market": market, "code": canonical}),
        "name": history[0].get("name") or (member.name if member is not None else canonical),
    }
    return jsonable_encoder({
        "market": market,
        "trade_date": resolved,
        "metadata": metadata,
        "latest": history[0],
        "history": history,
        "market_context": summary,
    })


__all__ = ["router"]
