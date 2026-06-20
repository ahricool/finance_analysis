from __future__ import annotations

from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from finance_analysis.interfaces.api.deps import get_effective_uid
from finance_analysis.interfaces.api.v1.schemas.calendar import (
    CalendarEntryCreate,
    CalendarEntryListResponse,
    CalendarEntryResponse,
    CalendarEntryUpdate,
)
from finance_analysis.database.repositories.calendar import CalendarRepo
from finance_analysis.core.time import DEFAULT_DISPLAY_TIMEZONE, validate_display_timezone

router = APIRouter()


def _repo() -> CalendarRepo:
    return CalendarRepo()


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
