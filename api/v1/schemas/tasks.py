# -*- coding: utf-8 -*-
"""Schemas for the task center APIs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TaskUserSummary(BaseModel):
    uid: int
    username: str
    email: str
    role: str


class TaskRunBase(BaseModel):
    id: int
    task_id: str
    task_name: Optional[str] = None
    task_type: str
    uid: Optional[int] = None
    user: Optional[TaskUserSummary] = None
    source: str
    trigger_source: Optional[str] = None
    triggered_by_uid: Optional[int] = None
    triggered_by_user: Optional[TaskUserSummary] = None
    status: str
    progress: int
    message: Optional[str] = None
    scheduler_job_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    retry_count: int = 0
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    updated_at: Optional[str] = None
    duration_seconds: Optional[float] = None


class TaskRunDetail(TaskRunBase):
    payload: Optional[Any] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    task_log: Optional[str] = None


class TaskRunListResponse(BaseModel):
    items: List[TaskRunBase]
    total: int
    page: int
    page_size: int
    statistics: Dict[str, int] = Field(default_factory=dict)


class ScheduledTaskLatestRun(BaseModel):
    task_id: str
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    message: Optional[str] = None


class ScheduledTaskItem(BaseModel):
    job_id: str
    name: str
    description: str
    task_type: str
    schedule: str
    timezone: str
    scheduler_status: str
    next_run_time: Optional[str] = None
    allow_manual_run: bool
    latest_run: Optional[ScheduledTaskLatestRun] = None


class ScheduledTaskListResponse(BaseModel):
    items: List[ScheduledTaskItem]


class ScheduledTaskRunAccepted(BaseModel):
    task_id: str
    job_id: str
    status: str
    message: str


class DuplicateTaskResponse(BaseModel):
    error: str = "task_already_running"
    message: str
    existing_task_id: str
