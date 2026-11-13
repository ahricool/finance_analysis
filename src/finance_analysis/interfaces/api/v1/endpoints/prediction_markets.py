"""Catalog reads are DB-only; dynamic GETs may use public upstream and disposable Redis."""

from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query

from finance_analysis.database.repositories.prediction_markets import Repository
from finance_analysis.interfaces.api.deps import require_current_user, require_admin
from finance_analysis.interfaces.api.v1.schemas.prediction_markets import (
    EventPage,
    TagOverride,
    EventOverride,
    RunRequest,
    LiveResponse,
    HistoryResponse,
)
from finance_analysis.prediction_markets.live import get_live_service
from finance_analysis.prediction_markets.rules import import_slug

router = APIRouter(dependencies=[Depends(require_current_user)])


def repository():
    return Repository()


@router.get("/tags")
def tags(repo=Depends(repository)):
    items = repo.tags()
    return {"status": "ready" if items else "not_synced", "items": items}


def listing(repo, **kwargs):
    result = repo.list_events(**kwargs)
    return dict(status="ready" if result["total"] else "empty" if repo.tags(admin=True) else "not_synced", **result)


@router.get("/events", response_model=EventPage)
def events(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=30),
    keyword: str = "",
    tag_ids: list[str] = Query(default=[]),
    closed: bool | None = False,
    sort: Literal["updated", "deadline", "title"] = "updated",
    repo=Depends(repository),
):
    # Hidden tags must not become a public filtering channel.
    visible = {t["tag_id"] for t in repo.tags()}
    if set(tag_ids) - visible:
        raise HTTPException(422, "只能筛选可见标签")
    return listing(repo, page=page, page_size=page_size, keyword=keyword, tag_ids=tag_ids, closed=closed, sort=sort)


def stored(repo, event_id):
    event = repo.event(event_id)
    if not event or not event["retained"]:
        return {"status": "not_synced"}
    return None


@router.get("/events/{event_id}/live", response_model=LiveResponse)
def live(event_id: str, repo=Depends(repository)):
    return stored(repo, event_id) or get_live_service().live(event_id)


@router.get("/events/{event_id}/history", response_model=HistoryResponse)
def history(
    event_id: str,
    market_id: str,
    outcome_id: str,
    window: Literal["1d", "1w", "1m", "max"] = "1w",
    repo=Depends(repository),
):
    status = stored(repo, event_id)
    if status:
        return status
    try:
        return get_live_service().history(event_id, market_id, outcome_id, window)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/admin/tags", dependencies=[Depends(require_admin)])
def admin_tags(repo=Depends(repository)):
    return {"items": repo.tags(admin=True)}


@router.get("/admin/events", response_model=EventPage, dependencies=[Depends(require_admin)])
def admin_events(
    page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=30), keyword: str = "", repo=Depends(repository)
):
    return listing(repo, page=page, page_size=page_size, keyword=keyword, closed=None, admin=True)


@router.patch("/admin/tags/{tag_id}", dependencies=[Depends(require_admin)])
def override_tag(tag_id: str, body: TagOverride, repo=Depends(repository)):
    try:
        repo.set_tag(tag_id, body.visible)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"status": "updated"}


@router.patch("/admin/events/{event_id}", dependencies=[Depends(require_admin)])
def override_event(event_id: str, body: EventOverride, repo=Depends(repository)):
    try:
        repo.set_event(event_id, body.retained)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"status": "updated"}


@router.post("/admin/run", status_code=202)
def run(body: RunRequest, admin=Depends(require_admin)):
    from finance_analysis.tasks.celery.jobs.polymarket.tasks import polymarket_catalog_sync

    try:
        slug = import_slug(body.slug) if body.slug else None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    result = polymarket_catalog_sync.apply_async(
        queue="ingestion", kwargs={"slug": slug, "_trigger_source": "manual", "_triggered_by_uid": admin.id}
    )
    return {"status": "queued", "task_id": result.id}
