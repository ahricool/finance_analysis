from __future__ import annotations

from datetime import date as date_type, timedelta
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request

from finance_analysis.interfaces.api.deps import get_effective_uid
from finance_analysis.interfaces.api.v1.schemas.calendar import (
    CalendarEntryCreate,
    CalendarEntryListResponse,
    CalendarEntryResponse,
    CalendarSummaryItem,
    CalendarSummaryResponse,
    CalendarEntryUpdate,
)
from finance_analysis.interfaces.api.v1.schemas.market_calendar import (
    FinanceEventCreate,
    FinanceEventListResponse,
    FinanceEventResponse,
)
from finance_analysis.database.repositories.calendar import CalendarRepo
from finance_analysis.database.repositories.market_calendar_event import MarketCalendarEventRepo
from finance_analysis.core.time import DEFAULT_DISPLAY_TIMEZONE, validate_display_timezone

router = APIRouter()
MAX_SUMMARY_DAYS = 31


def _repo() -> CalendarRepo:
    return CalendarRepo()


def _event_repo() -> MarketCalendarEventRepo:
    return MarketCalendarEventRepo()


def _date_span(start_date: date_type, end_date: date_type) -> list[date_type]:
    return [start_date + timedelta(days=offset) for offset in range((end_date - start_date).days + 1)]


@router.get('/events', response_model=FinanceEventListResponse, summary='按日期获取财经事件')
def list_finance_events(
    query_date: date_type = Query(..., alias='date', description='查询日期 YYYY-MM-DD'),
    timezone: str = Query(DEFAULT_DISPLAY_TIMEZONE, description='Asia/Shanghai | America/New_York'),
    market: Optional[str] = Query(None, description='市场，例如 US'),
    calendar_type: Optional[str] = Query(None, description='事件类型，例如 earnings'),
):
    try:
        validate_display_timezone(timezone)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_timezone", "message": str(exc)},
        ) from exc
    items = _event_repo().list_events_by_date(
        query_date,
        market=market,
        calendar_type=calendar_type,
    )
    return FinanceEventListResponse(
        date=query_date.isoformat(),
        items=[FinanceEventResponse.model_validate(i) for i in items],
        total=len(items),
    )


@router.post('/events', response_model=FinanceEventResponse, status_code=201, summary='手动新增财经事件')
def create_finance_event(body: FinanceEventCreate):
    result = _event_repo().upsert_event(
        {
            **body.model_dump(),
            "provider": "manual",
            "provider_event_id": str(uuid4()),
        }
    )
    return FinanceEventResponse.model_validate(result.event)


@router.get('/summary', response_model=CalendarSummaryResponse, summary='按日期范围获取日历数量统计')
def get_calendar_summary(
    http_request: Request,
    start_date: date_type = Query(..., description='开始日期 YYYY-MM-DD'),
    end_date: date_type = Query(..., description='结束日期 YYYY-MM-DD'),
    timezone: str = Query(DEFAULT_DISPLAY_TIMEZONE, description='Asia/Shanghai | America/New_York'),
):
    if end_date < start_date:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_date_range",
                "message": "end_date must be greater than or equal to start_date",
            },
        )
    day_count = (end_date - start_date).days + 1
    if day_count > MAX_SUMMARY_DAYS:
        raise HTTPException(
            status_code=400,
            detail={"error": "date_range_too_large", "message": f"date range must be <= {MAX_SUMMARY_DAYS} days"},
        )
    try:
        timezone_name = validate_display_timezone(timezone)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_timezone", "message": str(exc)},
        ) from exc

    uid = get_effective_uid(http_request)
    event_counts = _event_repo().count_events_by_date_range(start_date, end_date)
    entry_counts = _repo().count_by_date_range(start_date, end_date, timezone_name=timezone_name, uid=uid)
    return CalendarSummaryResponse(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        items=[
            CalendarSummaryItem(
                date=day.isoformat(),
                finance_event_count=event_counts.get(day, 0),
                calendar_entry_count=entry_counts.get(day, 0),
            )
            for day in _date_span(start_date, end_date)
        ],
    )


@router.get('', response_model=CalendarEntryListResponse, summary='按日期获取日历记录')
def list_calendar_entries(
    http_request: Request,
    query_date: Optional[date_type] = Query(None, alias='date', description='查询日期 YYYY-MM-DD'),
    legacy_time: Optional[date_type] = Query(None, alias='time', description='兼容旧参数；请改用 date'),
    timezone: str = Query(DEFAULT_DISPLAY_TIMEZONE, description='Asia/Shanghai | America/New_York'),
):
    uid = get_effective_uid(http_request)
    day = query_date or legacy_time
    if day is None:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_params", "message": "date is required"},
        )
    try:
        timezone_name = validate_display_timezone(timezone)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_timezone", "message": str(exc)},
        ) from exc
    items = _repo().list_by_date(day, timezone_name=timezone_name, uid=uid)
    return CalendarEntryListResponse(
        date=day.isoformat(),
        items=[CalendarEntryResponse.model_validate(i) for i in items],
        total=len(items),
    )


@router.post('', response_model=CalendarEntryResponse, status_code=201, summary='新增日历记录')
def create_calendar_entry(http_request: Request, body: CalendarEntryCreate):
    uid = get_effective_uid(http_request)
    item = _repo().create(
        uid=uid,
        time=body.time,
        title=body.title,
        content=body.content,
        type=body.type,
    )
    return CalendarEntryResponse.model_validate(item)


@router.put('/{item_id}', response_model=CalendarEntryResponse, summary='更新日历记录')
def update_calendar_entry(http_request: Request, item_id: int, body: CalendarEntryUpdate):
    uid = get_effective_uid(http_request)
    item = _repo().update(
        item_id,
        uid=uid,
        title=body.title,
        content=body.content,
        type=body.type,
    )
    if item is None:
        raise HTTPException(status_code=404, detail='未找到该记录')
    return CalendarEntryResponse.model_validate(item)


@router.delete('/{item_id}', status_code=204, summary='删除日历记录')
def delete_calendar_entry(http_request: Request, item_id: int):
    uid = get_effective_uid(http_request)
    deleted = _repo().delete(item_id, uid=uid)
    if not deleted:
        raise HTTPException(status_code=404, detail='未找到该记录')
