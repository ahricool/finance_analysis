"""Database-only reads; administrators submit asynchronous close/backfill jobs."""

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from finance_analysis.database.repositories.market_sentiment import MarketSentimentRepository
from finance_analysis.database.repositories.industry_strength import IndustryStrengthRepository
from finance_analysis.interfaces.api.deps import require_current_user, require_admin
from finance_analysis.interfaces.api.v1.schemas.market_sentiment import (
    OverviewResponse,
    HistoryResponse,
    PoolResponse,
    PoolKind,
    RunRequest,
    RunResponse,
    LadderResponse,
)
from finance_analysis.market_sentiment.calendar import expected_date, sessions_through, validate_day

router = APIRouter(dependencies=[Depends(require_current_user)])


def get_repository():
    return MarketSentimentRepository()


def get_industry_repository():
    return IndustryStrengthRepository()


@router.get("/overview", response_model=OverviewResponse)
def overview(trade_date: date | None = None, repo=Depends(get_repository), industries=Depends(get_industry_repository)):
    row = repo.overview(trade_date)
    day = date.fromisoformat(row["trade_date"]) if row else trade_date
    top = industries.ranking(day, limit=5) if day else []
    return {
        "trade_date": day,
        "expected_trade_date": expected_date(),
        "observation": row,
        "industry_top": [
            {k: r[k] for k in ("trade_date", "industry_code", "industry_name", "strength_score", "state")} for r in top
        ],
    }


@router.get("/history", response_model=HistoryResponse)
def history(end_date: date | None = None, days: int = Query(30, ge=1, le=60), repo=Depends(get_repository)):
    latest = repo.overview() if end_date is None else None
    end = end_date or (date.fromisoformat(latest["trade_date"]) if latest else expected_date())
    dates = sessions_through(end, days)
    rows = repo.history(dates)
    return {"dates": dates, "items": [rows.get(d) for d in dates]}


@router.get("/dates", response_model=list[date])
def dates(repo=Depends(get_repository)):
    return repo.dates()


@router.get("/pool", response_model=PoolResponse)
def pool(
    trade_date: date | None = None,
    kind: PoolKind = "limit_up",
    board: str | None = None,
    q: str = Query("", max_length=100),
    reason: str | None = Query(None, max_length=2000),
    scope: str = Query("main", pattern="^(main|all)$"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    repo=Depends(get_repository),
):
    if board is not None and board not in {"1", "2", "3", "4", "5", "6", "7+"}:
        raise HTTPException(422, "Unsupported board")
    row = repo.overview() if trade_date is None else None
    day = trade_date or (date.fromisoformat(row["trade_date"]) if row else None)
    source = repo.source(day, kind) if day else None
    rows = source["items"] if source else []
    if kind == "limit_up":
        if scope == "main":
            rows = [r for r in rows if r["in_scope"] is True]
        if board:
            rows = [
                r
                for r in rows
                if r["consecutive_boards"] is not None
                and (r["consecutive_boards"] >= 7 if board == "7+" else r["consecutive_boards"] == int(board))
            ]
        if reason is not None:
            rows = [r for r in rows if r["reason_group"] == reason]
    if q:
        rows = [r for r in rows if q.casefold() in f"{r['thscode']} {r.get('name', '')}".casefold()]
    return {
        "trade_date": day,
        "kind": kind,
        "available": source is not None,
        "total": len(rows) if source else None,
        "upstream_total": source["total"] if source else None,
        "page": page,
        "size": size,
        "items": rows[(page - 1) * size : page * size],
        "basis": "main" if kind == "limit_up" and scope == "main" else "upstream_all",
    }


@router.get("/ladder", response_model=LadderResponse)
def ladder(as_of: date | None = None, repo=Depends(get_repository)):
    return {"as_of": as_of, "source": repo.ladder(as_of), "basis": "official_limited_sample_max_4"}


@router.post("/run", status_code=202, response_model=RunResponse)
def run(body: RunRequest, user=Depends(require_admin)):
    if body.trade_date:
        try:
            validate_day(body.trade_date)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    from finance_analysis.tasks.celery.jobs.market_sentiment.tasks import run_market_sentiment_cn
    from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition

    definition = require_scheduled_task_definition("market_sentiment_cn")
    try:
        task = run_market_sentiment_cn.apply_async(
            kwargs={**body.model_dump(mode="json"), "_trigger_source": "manual", "_triggered_by_uid": user.id},
            queue=definition.queue,
            expires=definition.expires,
        )
    except Exception:
        raise HTTPException(503, "市场情绪任务提交失败") from None
    return {"task_id": task.id, "status": "pending"}
