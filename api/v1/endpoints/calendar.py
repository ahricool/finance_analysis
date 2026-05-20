from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from api.v1.schemas.calendar import (
    CalendarSignalCreate,
    CalendarSignalListResponse,
    CalendarSignalResponse,
    CalendarSignalUpdate,
)
from src.repositories.calendar_signal_repo import CalendarSignalRepo

router = APIRouter()


def _repo() -> CalendarSignalRepo:
    return CalendarSignalRepo()


@router.get('', response_model=CalendarSignalListResponse, summary='按日期获取日历信号')
def list_calendar_signals(signal_date: date = Query(..., description='查询日期 YYYY-MM-DD')):
    items = _repo().list_by_date(signal_date)
    return CalendarSignalListResponse(
        date=signal_date,
        items=[CalendarSignalResponse.model_validate(i) for i in items],
        total=len(items),
    )


@router.post('', response_model=CalendarSignalResponse, status_code=201, summary='新增日历信号')
def create_calendar_signal(body: CalendarSignalCreate):
    item = _repo().create(
        signal_date=body.signal_date,
        title=body.title,
        content=body.content,
        signal_type=body.signal_type,
    )
    return CalendarSignalResponse.model_validate(item)


@router.put('/{item_id}', response_model=CalendarSignalResponse, summary='更新日历信号')
def update_calendar_signal(item_id: int, body: CalendarSignalUpdate):
    item = _repo().update(
        item_id=item_id,
        title=body.title,
        content=body.content,
        signal_type=body.signal_type,
    )
    if item is None:
        raise HTTPException(status_code=404, detail='未找到该信号')
    return CalendarSignalResponse.model_validate(item)


@router.delete('/{item_id}', status_code=204, summary='删除日历信号')
def delete_calendar_signal(item_id: int):
    deleted = _repo().delete(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail='未找到该信号')
