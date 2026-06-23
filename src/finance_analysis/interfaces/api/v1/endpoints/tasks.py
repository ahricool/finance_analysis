# -*- coding: utf-8 -*-
"""Task center endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from finance_analysis.interfaces.api.deps import require_admin, require_current_user
from finance_analysis.interfaces.api.v1.schemas.tasks import (
    DuplicateTaskResponse,
    ScheduledTaskListResponse,
    ScheduledTaskRunAccepted,
    TaskRunDetail,
    TaskRunListResponse,
)
from finance_analysis.database.models.user import User
from finance_analysis.tasks.service import (
    DuplicateScheduledTaskError,
    ManualRunNotAllowedError,
    ScheduledTaskNotFoundError,
    ScheduledTaskService,
    SchedulerUnavailableError,
    TaskQueryService,
)

router = APIRouter()


def _parse_statuses(status_value: Optional[str]) -> Optional[List[str]]:
    if not status_value:
        return None
    values = [item.strip().lower() for item in status_value.split(",") if item.strip()]
    return values or None


@router.get("/scheduled", response_model=ScheduledTaskListResponse)
async def list_scheduled_tasks(_: User = Depends(require_admin)):
    service = ScheduledTaskService()
    return {"items": service.list_scheduled_tasks()}


@router.post(
    "/scheduled/{job_id}/run",
    response_model=ScheduledTaskRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses={409: {"model": DuplicateTaskResponse}},
)
async def run_scheduled_task(job_id: str, admin: User = Depends(require_admin)):
    service = ScheduledTaskService()
    try:
        return service.run_scheduled_task_now(job_id=job_id, triggered_by_uid=admin.id)
    except ScheduledTaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scheduled task not found") from exc
    except ManualRunNotAllowedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DuplicateScheduledTaskError as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": "task_already_running",
                "message": exc.message,
                "existing_task_id": exc.existing_task_id,
            },
        )
    except SchedulerUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc) or "Scheduler unavailable") from exc


@router.get("", response_model=TaskRunListResponse)
async def list_task_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status_value: Optional[str] = Query(None, alias="status"),
    task_type: Optional[str] = None,
    source: Optional[str] = None,
    trigger_source: Optional[str] = None,
    scheduler_job_id: Optional[str] = None,
    keyword: Optional[str] = None,
    started_from: Optional[datetime] = None,
    started_to: Optional[datetime] = None,
    uid: Optional[int] = None,
    current_user: User = Depends(require_current_user),
):
    is_admin = current_user.role == "admin"
    service = TaskQueryService()
    return service.list_runs(
        is_admin=is_admin,
        current_uid=current_user.id,
        page=page,
        page_size=page_size,
        statuses=_parse_statuses(status_value),
        uid=uid if is_admin else None,
        task_type=task_type,
        source=source,
        trigger_source=trigger_source,
        scheduler_job_id=scheduler_job_id,
        keyword=keyword,
        started_from=started_from,
        started_to=started_to,
    )


@router.get("/{task_id}", response_model=TaskRunDetail)
async def get_task_run_detail(task_id: str, current_user: User = Depends(require_current_user)):
    is_admin = current_user.role == "admin"
    service = TaskQueryService()
    payload = service.get_run_detail(task_id=task_id, is_admin=is_admin, current_uid=current_user.id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return payload
