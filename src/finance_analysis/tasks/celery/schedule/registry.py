# -*- coding: utf-8 -*-
"""Schedule registry used by Beat, routes, and the task center."""

from __future__ import annotations

from typing import Any, Optional

from .constants import ALL_QUEUES
from .definitions import SCHEDULED_TASK_DEFINITIONS, ScheduledTaskDefinition

_DEFINITIONS_BY_JOB_ID = {item.job_id: item for item in SCHEDULED_TASK_DEFINITIONS}
_DEFINITIONS_BY_TASK_NAME = {item.celery_task_name: item for item in SCHEDULED_TASK_DEFINITIONS}

if len(_DEFINITIONS_BY_JOB_ID) != len(SCHEDULED_TASK_DEFINITIONS):
    raise ValueError("Scheduled task job IDs must be unique")
if len(_DEFINITIONS_BY_TASK_NAME) != len(SCHEDULED_TASK_DEFINITIONS):
    raise ValueError("Scheduled Celery task names must be unique")


def get_scheduled_task_definitions() -> list[ScheduledTaskDefinition]:
    return list(SCHEDULED_TASK_DEFINITIONS)


def get_scheduled_task_definition(job_id: str) -> Optional[ScheduledTaskDefinition]:
    return _DEFINITIONS_BY_JOB_ID.get(job_id)


def require_scheduled_task_definition(job_id: str) -> ScheduledTaskDefinition:
    definition = get_scheduled_task_definition(job_id)
    if definition is None:
        raise KeyError(f"Unknown scheduled task job_id: {job_id}")
    return definition


def get_definition_by_task_name(task_name: str) -> Optional[ScheduledTaskDefinition]:
    return _DEFINITIONS_BY_TASK_NAME.get(task_name)


def build_beat_schedule() -> dict[str, dict[str, Any]]:
    schedule: dict[str, dict[str, Any]] = {}
    for definition in SCHEDULED_TASK_DEFINITIONS:
        if not definition.enabled:
            continue
        crontabs = definition.crontabs()
        for index, cron in enumerate(crontabs):
            entry_key = definition.job_id if len(crontabs) == 1 else f"{definition.job_id}__{index}"
            schedule[entry_key] = {
                "task": definition.celery_task_name,
                "schedule": cron,
                "options": {"queue": definition.queue, "expires": definition.expires},
                "kwargs": {
                    "scheduler_job_id": definition.job_id,
                    "_trigger_source": "scheduler",
                },
            }
    return schedule


def build_task_routes() -> dict[str, dict[str, str]]:
    return {
        definition.celery_task_name: {"queue": definition.queue}
        for definition in SCHEDULED_TASK_DEFINITIONS
    }


def get_task_queues() -> tuple[str, ...]:
    return ALL_QUEUES


__all__ = [
    "build_beat_schedule",
    "build_task_routes",
    "get_definition_by_task_name",
    "get_scheduled_task_definition",
    "get_scheduled_task_definitions",
    "get_task_queues",
    "require_scheduled_task_definition",
]
