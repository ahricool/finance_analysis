# -*- coding: utf-8 -*-
"""Celery application factory and shared instance."""

from __future__ import annotations

import logging
import uuid
from contextlib import AbstractContextManager
from typing import Any, Dict, Optional

from celery import Celery
from celery.signals import beat_init
from celery.signals import setup_logging as celery_setup_logging
from celery.signals import before_task_publish, task_failure, task_postrun, task_prerun, worker_process_init

from finance_analysis.config import load_env
from finance_analysis.database.config import get_database_config
from finance_analysis.core.logging import ensure_backend_logging, task_logging_context
from finance_analysis.core.paths import ensure_data_directories
from finance_analysis.tasks.celery.schedule import (
    QUEUE_DEFAULT,
    build_beat_schedule,
    build_task_routes,
    get_definition_by_task_name,
)
from finance_analysis.tasks.lifecycle import TaskLifecycleMetadata, get_task_lifecycle_service, is_tracked_callable

CELERY_APP_NAME = "finance_analysis"
logger = logging.getLogger(__name__)
_TASK_LOG_CONTEXTS: Dict[str, AbstractContextManager[logging.Logger]] = {}


def configure_celery_logging() -> None:
    """Configure Celery process logging without relying on the CLI --loglevel flag."""
    ensure_data_directories()
    ensure_backend_logging(service="celery", log_prefix="celery")


@celery_setup_logging.connect
def _on_celery_setup_logging(**_: Any) -> None:
    configure_celery_logging()


@worker_process_init.connect
def _on_worker_process_init(**_: Any) -> None:
    configure_celery_logging()


def _resolve_celery_task_id(task_id: Optional[str], task: Any = None) -> str:
    if task_id:
        return str(task_id)
    request = getattr(task, "request", None)
    request_id = getattr(request, "id", None)
    if request_id:
        return str(request_id)
    return uuid.uuid4().hex


@task_prerun.connect
def _start_task_file_logging(task_id: str, task: Any, **_: Any) -> None:
    if is_tracked_callable(task):
        return
    task_name = getattr(task, "name", None) or "celery_task"
    resolved_task_id = _resolve_celery_task_id(task_id, task)
    context = task_logging_context(task_name, task_id=resolved_task_id, celery=True)
    context.__enter__()
    _TASK_LOG_CONTEXTS[resolved_task_id] = context
    logger.info("Celery task started: task_id=%s task_name=%s", resolved_task_id, task_name)


@task_postrun.connect
def _stop_task_file_logging(task_id: str, task: Any, state: str, **_: Any) -> None:
    if is_tracked_callable(task):
        return
    task_name = getattr(task, "name", None) or "celery_task"
    resolved_task_id = _resolve_celery_task_id(task_id, task)
    logger.info("Celery task finished: task_id=%s task_name=%s state=%s", resolved_task_id, task_name, state)
    context = _TASK_LOG_CONTEXTS.pop(resolved_task_id, None)
    if context is not None:
        context.__exit__(None, None, None)


@task_failure.connect
def _log_task_failure(task_id: str, exception: BaseException, sender: Any, **_: Any) -> None:
    task_name = getattr(sender, "name", None) or "celery_task"
    resolved_task_id = _resolve_celery_task_id(task_id, sender)
    logger.exception(
        "Celery task failed: task_id=%s task_name=%s exception=%r",
        resolved_task_id,
        task_name,
        exception,
        exc_info=(type(exception), exception, exception.__traceback__),
    )


@before_task_publish.connect
def _create_pending_task_record(
    sender: Optional[str] = None,
    headers: Optional[Dict[str, Any]] = None,
    body: Any = None,
    **_: Any,
) -> None:
    headers = headers or {}
    task_id = str(headers.get("id") or uuid.uuid4().hex)
    task_name = str(sender or headers.get("task") or "celery_task")
    payload = _extract_publish_payload(body)
    kwargs = payload.get("kwargs") if isinstance(payload, dict) else {}
    if not isinstance(kwargs, dict):
        kwargs = {}

    definition = get_definition_by_task_name(task_name)
    if definition is not None:
        # Beat (or a manual submission) is publishing a registered periodic task;
        # seed the pending TaskRecord with the stable job_id and scheduler metadata
        # so the single record matches what the worker's ``track_task`` writes.
        # ``dedupe_key`` is intentionally omitted here: manual runs pre-create the
        # record (with the dedupe key) before publishing, and ``ensure_record``
        # only resolves uniqueness conflicts by ``task_id``.
        get_task_lifecycle_service().create_pending(
            task_id=task_id,
            metadata=TaskLifecycleMetadata(
                task_type=definition.task_type,
                task_name=definition.name,
                source="celery",
                trigger_source=str(kwargs.get("_trigger_source") or "scheduler"),
                triggered_by_uid=_safe_int(kwargs.get("_triggered_by_uid")),
                scheduler_job_id=str(kwargs.get("scheduler_job_id") or definition.job_id),
            ),
            payload=payload,
            message="任务已加入队列",
            retry_count=_safe_int(headers.get("retries")) or 0,
        )
        return

    get_task_lifecycle_service().create_pending(
        task_id=task_id,
        metadata=TaskLifecycleMetadata(
            task_type=str(kwargs.get("task_type") or _infer_task_type(task_name)),
            task_name=task_name,
            source=str(kwargs.get("source") or ("celery_manual" if task_name.startswith("analysis.") else "celery")),
            uid=_safe_int(kwargs.get("owner_uid")),
        ),
        payload=payload,
        message="任务已加入队列",
        retry_count=_safe_int(headers.get("retries")) or 0,
    )


@beat_init.connect
def _on_beat_init(**_: Any) -> None:
    """Start the Redis heartbeat writer when the Beat process boots."""
    from finance_analysis.tasks.celery.heartbeat import start_beat_heartbeat

    configure_celery_logging()
    start_beat_heartbeat()


def _extract_publish_payload(body: Any) -> Dict[str, Any]:
    if isinstance(body, (list, tuple)) and len(body) >= 2:
        return {"args": body[0], "kwargs": body[1]}
    if isinstance(body, dict):
        return body
    return {"body": repr(body)}


def _infer_task_type(task_name: str) -> str:
    mapping = {
        "analysis.run_stock_analysis": "stock_analysis",
        "analysis.run_market_review": "market_review",
        "analysis.run_batch_analysis": "batch_analysis",
        "demo.add": "demo_add",
    }
    return mapping.get(task_name, task_name)


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def create_celery_app() -> Celery:
    """Build a Celery app using the project Redis URL as broker and result backend."""
    load_env()
    config = get_database_config()
    app = Celery(
        CELERY_APP_NAME,
        broker=config.redis_url,
        backend=config.redis_url,
        include=[
            "finance_analysis.tasks.celery.jobs.demo",
            "finance_analysis.tasks.celery.jobs.analysis",
            "finance_analysis.tasks.celery.jobs.scheduled",
            "finance_analysis.tasks.celery.jobs.market_calendar",
        ],
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="Asia/Shanghai",
        enable_utc=True,
        task_track_started=True,
        # Truly disable broker prefetch (Celery 5.5+): the worker reserves at most
        # one message at a time and never hoards future-scheduled deliveries.
        worker_disable_prefetch=True,
        # Queue topology — a single worker still consumes all of these.
        task_default_queue=QUEUE_DEFAULT,
        task_routes=build_task_routes(),
        # Beat schedule and per-task timezones come straight from the registry.
        beat_schedule=build_beat_schedule(),
    )
    return app


celery_app = create_celery_app()
