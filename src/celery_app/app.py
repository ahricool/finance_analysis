# -*- coding: utf-8 -*-
"""Celery application factory and shared instance."""

from __future__ import annotations

import logging
import uuid
from contextlib import AbstractContextManager
from typing import Any, Dict, Optional

from celery import Celery
from celery.signals import setup_logging as celery_setup_logging
from celery.signals import task_failure, task_postrun, task_prerun, worker_process_init

from src.config import get_config, setup_env
from src.logging_config import ensure_backend_logging, task_logging_context

CELERY_APP_NAME = "finance_analysis"
logger = logging.getLogger(__name__)
_TASK_LOG_CONTEXTS: Dict[str, AbstractContextManager[logging.Logger]] = {}


def configure_celery_logging() -> None:
    """Configure Celery process logging without relying on the CLI --loglevel flag."""
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
    task_name = getattr(task, "name", None) or "celery_task"
    resolved_task_id = _resolve_celery_task_id(task_id, task)
    context = task_logging_context(task_name, task_id=resolved_task_id, celery=True)
    context.__enter__()
    _TASK_LOG_CONTEXTS[resolved_task_id] = context
    logger.info("Celery task started: task_id=%s task_name=%s", resolved_task_id, task_name)


@task_postrun.connect
def _stop_task_file_logging(task_id: str, task: Any, state: str, **_: Any) -> None:
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


def create_celery_app() -> Celery:
    """Build a Celery app using the project Redis URL as broker and result backend."""
    setup_env()
    config = get_config()
    app = Celery(
        CELERY_APP_NAME,
        broker=config.redis_url,
        backend=config.redis_url,
        include=[
            "src.celery_app.tasks.demo",
            "src.celery_app.tasks.analysis",
        ],
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="Asia/Shanghai",
        enable_utc=True,
        task_track_started=True,
    )
    return app


celery_app = create_celery_app()
