"""Public market timeline: identical content for every user, always newest first."""

from datetime import date as Date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from finance_analysis.core.time import DEFAULT_DISPLAY_TIMEZONE, validate_display_timezone
from finance_analysis.timeline.cursor import InvalidTimelineCursor, TimelineCursor
from finance_analysis.timeline.dto import CalendarType, Category, Importance, TimelineList  # pragma: allowlist secret
from finance_analysis.timeline.service import TimelineService  # pragma: allowlist secret

router = APIRouter()


def timeline_query(
    end_date: Date | None = None,
    timezone: str = DEFAULT_DISPLAY_TIMEZONE,
    market: str | None = None,
    category: Category | None = None,
    calendar_type: CalendarType | None = None,
    importance: Importance | None = None,
):
    """``end_date`` is a cutoff: keep everything up to the end of that display-timezone day."""
    try:
        validate_display_timezone(timezone)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return dict(
        end_date=end_date,
        timezone_name=timezone,
        market=market,
        category=category,
        calendar_type=calendar_type,
        importance=importance,
    )


@router.get("", response_model=TimelineList)
def list_timeline(
    query: Annotated[dict, Depends(timeline_query)],
    cursor: str | None = Query(None, max_length=1024),
    limit: int = Query(20, ge=1, le=100),
):
    try:
        position = TimelineCursor.decode(cursor) if cursor is not None else None
    except InvalidTimelineCursor as exc:
        raise HTTPException(422, str(exc)) from exc
    return TimelineService().list(cursor=position, limit=limit, **query)
