# -*- coding: utf-8 -*-
"""Unified task lifecycle tracking for Celery tasks and queue state."""

from __future__ import annotations

import functools
import json
import logging
import os
import re
import traceback
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, TypeVar

from finance_analysis.core.logging import get_log_base_dir, get_task_log_file, task_logging_context
from finance_analysis.database.repositories.task_record import TaskRecordRepository
from finance_analysis.core.time import utc_now

logger = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable[..., Any])

MAX_PAYLOAD_CHARS = 8000
MAX_RESULT_CHARS = 12000
MAX_ERROR_CHARS = 24000
MAX_FAILURE_NOTIFICATION_STACK_CHARS = 6000
MAX_JSON_DEPTH = 6
MAX_JSON_ITEMS = 40
MAX_STRING_CHARS = 1000
SENSITIVE_KEY_TOKENS = ("token", "secret", "password", "authorization", "api_key", "apikey", "key")

CURRENT_TASK_ID: ContextVar[Optional[str]] = ContextVar("task_lifecycle_task_id", default=None)


class TaskExecutionStatus(str, Enum):
    """Persistent lifecycle states for task execution instances."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class TaskSkipped(Exception):
    """Raise from scheduled jobs when a run should be recorded as skipped."""


@dataclass
class TaskLifecycleMetadata:
    task_type: str
    task_name: str
    source: str
    uid: Optional[int] = None
    trigger_source: Optional[str] = None
    triggered_by_uid: Optional[int] = None
    scheduler_job_id: Optional[str] = None
    parent_task_id: Optional[str] = None


@dataclass(frozen=True)
class DeferredTaskResult:
    """Return a Celery result without closing its persisted task lifecycle."""

    value: Any
    message: str = "子任务已分发，等待最终结果"
    progress: int = 50


def defer_task_completion(
    value: Any,
    *,
    message: str | None = None,
    progress: int = 50,
) -> DeferredTaskResult:
    return DeferredTaskResult(
        value=value,
        message=message or "子任务已分发，等待最终结果",
        progress=progress,
    )


def get_current_task_id() -> Optional[str]:
    """Return the task id bound by ``track_task`` for the current execution context."""

    return CURRENT_TASK_ID.get()


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}...<truncated {len(value) - limit} chars>"


def _redact_error_text(value: str) -> str:
    text = value
    for token in SENSITIVE_KEY_TOKENS:
        text = re.sub(
            rf"({re.escape(token)}\s*[=:]\s*)([^\s,;]+)",
            r"\1***",
            text,
            flags=re.IGNORECASE,
        )
    return _truncate_text(text, MAX_ERROR_CHARS)


def _redact_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= MAX_JSON_DEPTH:
        return {"truncated": True, "reason": "max_depth"}
    if isinstance(value, Mapping):
        redacted: Dict[str, Any] = {}
        items = list(value.items())
        for key, nested in items[:MAX_JSON_ITEMS]:
            key_text = str(key)
            if any(token in key_text.lower() for token in SENSITIVE_KEY_TOKENS):
                redacted[key_text] = "***"
            else:
                redacted[key_text] = _redact_value(nested, depth=depth + 1)
        if len(items) > MAX_JSON_ITEMS:
            redacted["_truncated_items"] = len(items) - MAX_JSON_ITEMS
        return redacted
    if isinstance(value, (list, tuple, set)):
        values = list(value)
        result = [_redact_value(item, depth=depth + 1) for item in values[:MAX_JSON_ITEMS]]
        if len(values) > MAX_JSON_ITEMS:
            result.append({"truncated": True, "remaining_items": len(values) - MAX_JSON_ITEMS})
        return result
    if isinstance(value, str):
        return _truncate_text(value, MAX_STRING_CHARS)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return repr(value)


def _json_summary(value: Any, *, limit: int) -> Optional[str]:
    if value is None:
        return None
    try:
        redacted = _redact_value(value)
        text = json.dumps(redacted, ensure_ascii=False, default=str)
    except Exception:
        redacted = repr(value)
        text = json.dumps(redacted, ensure_ascii=False)
    if len(text) <= limit:
        return text
    preview_limit = max(200, limit - 120)
    return json.dumps(
        {
            "truncated": True,
            "preview": text[:preview_limit],
            "original_size": len(text),
        },
        ensure_ascii=False,
    )


def _relative_task_log_path(task_name: str, task_id: str, *, celery: bool) -> str:
    log_file = get_task_log_file(task_name, task_id, celery=celery)
    try:
        return str(log_file.relative_to(get_log_base_dir()))
    except ValueError:
        try:
            return str(log_file.relative_to(Path.cwd()))
        except ValueError:
            return str(log_file)


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


class TaskLifecycleService:
    """Best-effort DB lifecycle writer used by queue and decorators."""

    def __init__(self, repository: Optional[TaskRecordRepository] = None):
        self.repository = repository

    def create_pending(
        self,
        *,
        task_id: str,
        metadata: TaskLifecycleMetadata,
        payload: Optional[Any] = None,
        message: Optional[str] = None,
        progress: int = 0,
        task_log: Optional[str] = None,
        retry_count: int = 0,
        dedupe_key: Optional[str] = None,
    ) -> None:
        self._safe_write(
            "create pending task record",
            lambda repo: repo.ensure_record(
                task_id=task_id,
                task_type=metadata.task_type,
                task_name=metadata.task_name,
                uid=metadata.uid,
                source=metadata.source,
                status=TaskExecutionStatus.PENDING.value,
                payload=_json_summary(payload, limit=MAX_PAYLOAD_CHARS),
                message=message,
                progress=progress,
                task_log=task_log,
                parent_task_id=metadata.parent_task_id,
                retry_count=retry_count,
                scheduler_job_id=metadata.scheduler_job_id,
                dedupe_key=dedupe_key,
                trigger_source=metadata.trigger_source,
                triggered_by_uid=metadata.triggered_by_uid,
            ),
        )

    def mark_processing(
        self,
        *,
        task_id: str,
        metadata: TaskLifecycleMetadata,
        payload: Optional[Any] = None,
        message: Optional[str] = None,
        progress: int = 10,
        task_log: Optional[str] = None,
        retry_count: int = 0,
    ) -> None:
        self._safe_write(
            "mark task processing",
            lambda repo: repo.update_status(
                task_id=task_id,
                task_type=metadata.task_type,
                task_name=metadata.task_name,
                uid=metadata.uid,
                source=metadata.source,
                status=TaskExecutionStatus.PROCESSING.value,
                progress=progress,
                message=message,
                payload=_json_summary(payload, limit=MAX_PAYLOAD_CHARS),
                task_log=task_log,
                started_at=utc_now(),
                parent_task_id=metadata.parent_task_id,
                retry_count=retry_count,
                scheduler_job_id=metadata.scheduler_job_id,
                trigger_source=metadata.trigger_source,
                triggered_by_uid=metadata.triggered_by_uid,
            ),
        )

    def claim_active_dedupe_key(self, *, task_id: str, dedupe_key: str) -> bool:
        if (
            self.repository is None
            and os.getenv("PYTEST_CURRENT_TEST")
            and not os.getenv("FINANCE_TASK_RECORD_DB_TEST")
        ):
            return True
        try:
            return self._get_repository().claim_active_dedupe_key(task_id, dedupe_key)
        except Exception:
            logger.warning("Task lifecycle DB write failed while claiming dedupe key", exc_info=True)
            raise

    def mark_progress(self, *, task_id: str, progress: int, message: Optional[str] = None) -> None:
        self._safe_write(
            "update task progress",
            lambda repo: repo.update_status(
                task_id=task_id,
                status=TaskExecutionStatus.PROCESSING.value,
                progress=progress,
                message=message,
            ),
        )

    def mark_completed(
        self,
        *,
        task_id: str,
        metadata: TaskLifecycleMetadata,
        result: Optional[Any] = None,
        message: Optional[str] = None,
        progress: int = 100,
    ) -> None:
        self._safe_write(
            "mark task completed",
            lambda repo: repo.update_status(
                task_id=task_id,
                task_type=metadata.task_type,
                task_name=metadata.task_name,
                uid=metadata.uid,
                source=metadata.source,
                status=TaskExecutionStatus.COMPLETED.value,
                progress=progress,
                message=message,
                result=_json_summary(result, limit=MAX_RESULT_CHARS),
                finished_at=utc_now(),
                parent_task_id=metadata.parent_task_id,
                scheduler_job_id=metadata.scheduler_job_id,
                trigger_source=metadata.trigger_source,
                triggered_by_uid=metadata.triggered_by_uid,
            ),
        )

    def mark_skipped(
        self,
        *,
        task_id: str,
        metadata: TaskLifecycleMetadata,
        message: Optional[str] = None,
        result: Optional[Any] = None,
    ) -> None:
        self._safe_write(
            "mark task skipped",
            lambda repo: repo.update_status(
                task_id=task_id,
                task_type=metadata.task_type,
                task_name=metadata.task_name,
                uid=metadata.uid,
                source=metadata.source,
                status=TaskExecutionStatus.SKIPPED.value,
                progress=100,
                message=message,
                result=_json_summary(result, limit=MAX_RESULT_CHARS),
                finished_at=utc_now(),
                parent_task_id=metadata.parent_task_id,
                scheduler_job_id=metadata.scheduler_job_id,
                trigger_source=metadata.trigger_source,
                triggered_by_uid=metadata.triggered_by_uid,
            ),
        )

    def mark_cancelled(
        self,
        *,
        task_id: str,
        metadata: TaskLifecycleMetadata,
        message: Optional[str] = None,
    ) -> None:
        self._safe_write(
            "mark task cancelled",
            lambda repo: repo.update_status(
                task_id=task_id,
                task_type=metadata.task_type,
                task_name=metadata.task_name,
                uid=metadata.uid,
                source=metadata.source,
                status=TaskExecutionStatus.CANCELLED.value,
                progress=100,
                message=message,
                finished_at=utc_now(),
                parent_task_id=metadata.parent_task_id,
                scheduler_job_id=metadata.scheduler_job_id,
                trigger_source=metadata.trigger_source,
                triggered_by_uid=metadata.triggered_by_uid,
            ),
        )

    def mark_failed(
        self,
        *,
        task_id: str,
        metadata: TaskLifecycleMetadata,
        error: BaseException | str,
        message: Optional[str] = None,
    ) -> None:
        if isinstance(error, BaseException):
            error_text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        else:
            error_text = str(error)
        self._safe_write(
            "mark task failed",
            lambda repo: repo.update_status(
                task_id=task_id,
                task_type=metadata.task_type,
                task_name=metadata.task_name,
                uid=metadata.uid,
                source=metadata.source,
                status=TaskExecutionStatus.FAILED.value,
                progress=100,
                message=message,
                error=_redact_error_text(error_text),
                finished_at=utc_now(),
                parent_task_id=metadata.parent_task_id,
                scheduler_job_id=metadata.scheduler_job_id,
                trigger_source=metadata.trigger_source,
                triggered_by_uid=metadata.triggered_by_uid,
            ),
        )

    def _get_repository(self) -> TaskRecordRepository:
        if self.repository is None:
            self.repository = TaskRecordRepository()
        return self.repository

    def _safe_write(self, operation: str, callback: Callable[[TaskRecordRepository], Any]) -> None:
        if (
            self.repository is None
            and os.getenv("PYTEST_CURRENT_TEST")
            and not os.getenv("FINANCE_TASK_RECORD_DB_TEST")
        ):
            return
        try:
            callback(self._get_repository())
        except Exception as exc:
            logger.warning("Task lifecycle DB write failed during %s: %s", operation, exc, exc_info=True)


_DEFAULT_SERVICE = TaskLifecycleService()


def get_task_lifecycle_service() -> TaskLifecycleService:
    return _DEFAULT_SERVICE


def build_payload_from_call(args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    return {"args": list(args), "kwargs": dict(kwargs)}


def _send_task_failure_notification(
    *,
    task_id: str,
    metadata: TaskLifecycleMetadata,
    error: BaseException,
) -> None:
    try:
        from finance_analysis.notification.service import NotificationService

        reason = _redact_error_text(f"{type(error).__name__}: {error}")
        stack = _redact_error_text("".join(traceback.format_exception(type(error), error, error.__traceback__)))
        stack = _truncate_text(stack, MAX_FAILURE_NOTIFICATION_STACK_CHARS)
        content = "\n".join(
            [
                "**任务失败通知**",
                "",
                f"- 任务：{metadata.task_name}",
                f"- 类型：{metadata.task_type}",
                f"- 来源：{metadata.source}",
                f"- Task ID：{task_id}",
                f"- 失败原因：{reason}",
                "",
                "**调用栈**",
                "```text",
                stack,
                "```",
            ]
        )
        notification_key = f"task_failure:{task_id}"
        NotificationService().send(
            content,
            route_type="system_error",
            severity="error",
            dedup_key=notification_key,
            cooldown_key=notification_key,
        )
    except Exception as notify_exc:
        logger.warning(
            "Task failure notification failed for task_id=%s task_name=%s: %s",
            task_id,
            metadata.task_name,
            notify_exc,
            exc_info=True,
        )


def track_task(
    *,
    task_type: str,
    task_name: str,
    source: str,
    uid_getter: Optional[Callable[..., Optional[int]]] = None,
    task_id_getter: Optional[Callable[..., Optional[str]]] = None,
    task_name_getter: Optional[Callable[..., Optional[str]]] = None,
    trigger_source: Optional[str] = None,
    trigger_source_getter: Optional[Callable[..., Optional[str]]] = None,
    triggered_by_uid_getter: Optional[Callable[..., Optional[int]]] = None,
    scheduler_job_id: Optional[str] = None,
    record_result: bool = True,
    success_message: Optional[str] = None,
    strip_lifecycle_kwargs: bool = False,
    dedupe_key: Optional[str] = None,
) -> Callable[[F], F]:
    """Decorate task functions with persistent lifecycle tracking and task log context."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            task_id = _resolve_task_id(task_id_getter, args, kwargs)
            uid = _resolve_uid(uid_getter, args, kwargs)
            resolved_task_name = _resolve_task_name(task_name, task_name_getter, args, kwargs)
            resolved_trigger_source = _resolve_trigger_source(trigger_source, trigger_source_getter, args, kwargs)
            resolved_triggered_by_uid = _resolve_triggered_by_uid(triggered_by_uid_getter, args, kwargs)
            metadata = TaskLifecycleMetadata(
                task_type=task_type,
                task_name=resolved_task_name,
                source=source,
                uid=uid,
                trigger_source=resolved_trigger_source,
                triggered_by_uid=resolved_triggered_by_uid,
                scheduler_job_id=scheduler_job_id,
            )
            celery = source.startswith("celery")
            task_log = _relative_task_log_path(resolved_task_name, task_id, celery=celery)
            payload = build_payload_from_call(args, kwargs)
            retry_count = _resolve_retry_count()
            service = get_task_lifecycle_service()
            token = CURRENT_TASK_ID.set(task_id)
            with task_logging_context(resolved_task_name, task_id=task_id, celery=celery):
                service.mark_processing(
                    task_id=task_id,
                    metadata=metadata,
                    payload=payload,
                    message="任务执行中",
                    task_log=task_log,
                    retry_count=retry_count,
                )
                if dedupe_key and not service.claim_active_dedupe_key(task_id=task_id, dedupe_key=dedupe_key):
                    service.mark_skipped(
                        task_id=task_id,
                        metadata=metadata,
                        message=f"已有运行中的同类任务: {dedupe_key}",
                        result={"sync_status": "skipped", "dedupe_key": dedupe_key},
                    )
                    CURRENT_TASK_ID.reset(token)
                    return None
                try:
                    call_kwargs = _strip_lifecycle_kwargs(kwargs) if strip_lifecycle_kwargs else kwargs
                    result = func(*args, **call_kwargs)
                except TaskSkipped as exc:
                    service.mark_skipped(
                        task_id=task_id,
                        metadata=metadata,
                        message=str(exc) or "任务已跳过",
                    )
                    return None
                except Exception as exc:
                    service.mark_failed(task_id=task_id, metadata=metadata, error=exc, message=str(exc)[:200])
                    _send_task_failure_notification(task_id=task_id, metadata=metadata, error=exc)
                    raise
                else:
                    if isinstance(result, DeferredTaskResult):
                        service.mark_progress(
                            task_id=task_id,
                            progress=result.progress,
                            message=result.message,
                        )
                        return result.value
                    service.mark_completed(
                        task_id=task_id,
                        metadata=metadata,
                        result=result if record_result else None,
                        message=success_message or "任务执行完成",
                    )
                    return result
                finally:
                    CURRENT_TASK_ID.reset(token)

        wrapper._finance_tracked_task = True  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator


def _resolve_task_id(
    task_id_getter: Optional[Callable[..., Optional[str]]],
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> str:
    if task_id_getter is not None:
        try:
            task_id = task_id_getter(*args, **kwargs)
            if task_id:
                return str(task_id)
        except Exception:
            logger.debug("task_id_getter failed", exc_info=True)
    if kwargs.get("task_id"):
        return str(kwargs["task_id"])
    try:
        from celery import current_task

        request_id = getattr(getattr(current_task, "request", None), "id", None)
        if request_id:
            return str(request_id)
    except Exception:
        pass
    return uuid.uuid4().hex


def _resolve_uid(
    uid_getter: Optional[Callable[..., Optional[int]]],
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> Optional[int]:
    if uid_getter is not None:
        try:
            return _safe_int(uid_getter(*args, **kwargs))
        except Exception:
            logger.debug("uid_getter failed", exc_info=True)
    return _safe_int(kwargs.get("owner_uid"))


def _resolve_trigger_source(
    default: Optional[str],
    trigger_source_getter: Optional[Callable[..., Optional[str]]],
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> Optional[str]:
    if trigger_source_getter is not None:
        try:
            value = trigger_source_getter(*args, **kwargs)
            if value:
                return str(value)
        except Exception:
            logger.debug("trigger_source_getter failed", exc_info=True)
    value = kwargs.get("_trigger_source")
    return str(value) if value else default


def _resolve_triggered_by_uid(
    triggered_by_uid_getter: Optional[Callable[..., Optional[int]]],
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> Optional[int]:
    if triggered_by_uid_getter is not None:
        try:
            return _safe_int(triggered_by_uid_getter(*args, **kwargs))
        except Exception:
            logger.debug("triggered_by_uid_getter failed", exc_info=True)
    return _safe_int(kwargs.get("_triggered_by_uid"))


def _strip_lifecycle_kwargs(kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in kwargs.items()
        if key not in {"task_id", "_trigger_source", "_triggered_by_uid"}
    }


def _resolve_task_name(
    default: str,
    task_name_getter: Optional[Callable[..., Optional[str]]],
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> str:
    if task_name_getter is not None:
        try:
            task_name = task_name_getter(*args, **kwargs)
            if task_name:
                return str(task_name)
        except Exception:
            logger.debug("task_name_getter failed", exc_info=True)
    return default


def _resolve_retry_count() -> int:
    try:
        from celery import current_task

        return int(getattr(getattr(current_task, "request", None), "retries", 0) or 0)
    except Exception:
        return 0


def is_tracked_callable(value: Any) -> bool:
    run = getattr(value, "run", None)
    return bool(getattr(value, "_finance_tracked_task", False) or getattr(run, "_finance_tracked_task", False))
