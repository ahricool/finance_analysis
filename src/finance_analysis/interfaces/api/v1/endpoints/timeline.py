"""Public market timeline: identical content for every user, always newest first."""

from datetime import date as Date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from finance_analysis.core.time import DEFAULT_DISPLAY_TIMEZONE, validate_display_timezone
from finance_analysis.timeline.cursor import InvalidTimelineCursor, TimelineCursor
from finance_analysis.timeline.dto import CalendarType, Category, Importance, TimelineList  # pragma: allowlist secret
from finance_analysis.interfaces.api.deps import require_admin
from finance_analysis.interfaces.api.v1.schemas.earnings_outlook import OutlookDetail, OutlookTaskSubmitted
from finance_analysis.timeline.service import TimelineService  # pragma: allowlist secret

router = APIRouter()


def timeline_query(
    end_date: Date | None = None,
    timezone: str = DEFAULT_DISPLAY_TIMEZONE,
    high_confidence: bool = False,
    market: str | None = None,
    category: Category | None = None,
    calendar_type: CalendarType | None = None,
    importance: Importance | None = Query(
        None, description="最低重要性，包含所选等级及以上：low < normal < high < critical"
    ),
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
        high_confidence=high_confidence,
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


@router.get("/earnings/{event_id}/outlook", response_model=OutlookDetail)
def earnings_detail(event_id: int):
    from finance_analysis.database.repositories.earnings_outlook import EarningsOutlookRepository, display_summary
    from finance_analysis.core.time import utc_now
    from finance_analysis.earnings_outlook.rules import digest, schedule

    repo = EarningsOutlookRepository()
    event = repo.event(event_id)
    if not event or event.market != "US" or event.calendar_type != "earnings":
        raise HTTPException(404, "美股财报事件不存在")
    service = TimelineService(repo.db)
    members = service._members()
    detail = repo.detail(event_id)
    detail["summary"] = display_summary(event, repo.state(event_id), members, utc_now())
    for version in detail["versions"]:
        version["applicability"] = (
            "ineligible"
            if event.symbol not in members
            else "superseded" if version["schedule_hash"] != digest(schedule(event)) else "valid"
        )
    return detail


@router.post("/earnings/{event_id}/outlook/refresh", status_code=202, response_model=OutlookTaskSubmitted)
def refresh_earnings(event_id: int, user=Depends(require_admin)):
    from finance_analysis.database.repositories.earnings_outlook import EarningsOutlookRepository
    from finance_analysis.tasks.celery.jobs.earnings_outlook.tasks import earnings_outlook

    event = EarningsOutlookRepository().event(event_id)
    if not event or event.market != "US" or event.calendar_type != "earnings":
        raise HTTPException(404, "美股财报事件不存在")
    try:
        task = earnings_outlook.apply_async(
            kwargs={"event_id": event_id, "stage": "manual", "_trigger_source": "manual", "_triggered_by_uid": user.id},
            queue="analysis",
        )
    except Exception as exc:
        raise HTTPException(503, "财报前瞻任务提交失败") from exc
    return {"task_id": task.id, "status": "pending", "event_id": event_id}
