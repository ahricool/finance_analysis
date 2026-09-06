"""Unified investment timeline and user note endpoints."""

from datetime import date as Date
from datetime import datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from finance_analysis.core.time import DEFAULT_DISPLAY_TIMEZONE, validate_display_timezone
from finance_analysis.database.repositories.timeline import TimelineEntryRepo
from finance_analysis.interfaces.api.deps import get_effective_uid
from finance_analysis.interfaces.api.v1.schemas.timeline import NoteInput
from finance_analysis.timeline.dto import Actionability, Category, Importance, TimelineList, TimelineSummaryItem
from finance_analysis.timeline.service import TimelineService

router = APIRouter()


def timeline_query(
    request: Request,
    date: Date | None = None,
    start_date: Date | None = None,
    end_date: Date | None = None,
    timezone: str = DEFAULT_DISPLAY_TIMEZONE,
    market: str | None = None,
    category: Category | None = None,
    importance: Importance | None = None,
    actionability: Actionability | None = None,
):
    try:
        validate_display_timezone(timezone)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if date and (start_date or end_date):
        raise HTTPException(422, "date cannot be combined with start_date or end_date")
    today = datetime.now(ZoneInfo(timezone)).date()
    start = date or start_date or today - timedelta(days=7)
    end = date or end_date or today
    if end < start or (end - start).days > 366:
        raise HTTPException(422, "Date range must be ordered and at most 367 days")
    return dict(
        uid=get_effective_uid(request),
        start_date=start,
        end_date=end,
        timezone_name=timezone,
        market=market,
        category=category,
        importance=importance,
        actionability=actionability,
    )


@router.get("", response_model=TimelineList)
def list_timeline(
    query: Annotated[dict, Depends(timeline_query)], page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100)
):
    return TimelineService().list(page=page, limit=limit, **query)


@router.get("/summary", response_model=list[TimelineSummaryItem])
def timeline_summary(query: Annotated[dict, Depends(timeline_query)]):
    return TimelineService().summary(**query)


@router.post("/notes", status_code=201)
def create_note(request: Request, body: NoteInput):
    item = TimelineEntryRepo().create(uid=get_effective_uid(request), entry_type="manual_note", **body.model_dump())
    return {"id": item.id}


@router.put("/notes/{item_id}")
def update_note(request: Request, item_id: int, body: NoteInput):
    item = TimelineEntryRepo().update_note(item_id, uid=get_effective_uid(request), **body.model_dump())
    if item is None:
        raise HTTPException(404, "Note not found")
    return {"id": item.id}


@router.delete("/notes/{item_id}", status_code=204)
def delete_note(request: Request, item_id: int):
    if not TimelineEntryRepo().delete_note(item_id, uid=get_effective_uid(request)):
        raise HTTPException(404, "Note not found")
    return Response(status_code=204)
