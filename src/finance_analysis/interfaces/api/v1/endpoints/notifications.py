"""Authenticated, read-only message center."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from finance_analysis.core.time import coerce_aware_utc
from finance_analysis.database.repositories.notification import NotificationRepository
from finance_analysis.interfaces.api.deps import get_effective_uid
from finance_analysis.interfaces.api.v1.schemas.notifications import NotificationDetail, NotificationListResponse

router = APIRouter()


def get_notification_repository():
    return NotificationRepository()


@router.get("", response_model=NotificationListResponse)
def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None, max_length=300),
    route_type: Optional[str] = Query(None, max_length=32),
    severity: Optional[str] = Query(None, max_length=16),
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    uid: int = Depends(get_effective_uid),
    repo=Depends(get_notification_repository),
):
    if start_time and end_time and coerce_aware_utc(start_time) > coerce_aware_utc(end_time):
        raise HTTPException(422, "start_time must not exceed end_time")
    return repo.list_messages(
        uid=uid,
        page=page,
        page_size=page_size,
        keyword=keyword,
        route_type=route_type,
        severity=severity,
        start_time=start_time,
        end_time=end_time,
    )


@router.get("/{notification_id}", response_model=NotificationDetail)
def get_notification(
    notification_id: int,
    uid: int = Depends(get_effective_uid),
    repo=Depends(get_notification_repository),
):
    row = repo.get_message(notification_id, uid=uid)
    if row is None:
        raise HTTPException(404, "Notification not found")
    return row
