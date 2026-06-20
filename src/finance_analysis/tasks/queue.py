# -*- coding: utf-8 -*-
"""Celery-backed task submission service.

Task status and history are stored only in PostgreSQL ``task`` records. Redis is
used by Celery as broker/result backend, not as an application task-state store.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple

from finance_analysis.integrations.market_data.base import canonical_stock_code, normalize_stock_code

from finance_analysis.database.repositories.task_record import TaskRecordRepository
from finance_analysis.tasks.lifecycle import (
    MAX_PAYLOAD_CHARS,
    TaskLifecycleMetadata,
    _json_summary,
    get_task_lifecycle_service,
)
from finance_analysis.core.time import utc_now
from finance_analysis.analysis.metadata import SELECTION_SOURCES

logger = logging.getLogger(__name__)


def _dedupe_stock_code_key(stock_code: str) -> str:
    """Normalize equivalent stock-code shapes to one duplicate-detection key."""
    return canonical_stock_code(normalize_stock_code(stock_code))


def _dedupe_key_for_task(task_type: str, stock_code: str) -> str:
    if task_type == "stock_analysis":
        return f"stock_analysis:{_dedupe_stock_code_key(stock_code)}"
    return task_type


class TaskStatus(str, Enum):
    """Task status enumeration used by legacy API schemas."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


@dataclass
class TaskInfo:
    """Task information returned by submission helpers and API compatibility paths."""

    task_id: str
    stock_code: str
    stock_name: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    report_type: str = "detailed"
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    original_query: Optional[str] = None
    selection_source: Optional[str] = None
    owner_uid: Optional[int] = None
    task_type: Optional[str] = None
    source: Optional[str] = None
    trigger_source: Optional[str] = None
    dedupe_key: Optional[str] = None

    def __post_init__(self) -> None:
        if self.created_at is None:
            self.created_at = utc_now()

    def to_dict(self) -> Dict[str, Any]:
        from finance_analysis.core.time import utc_isoformat

        return {
            "task_id": self.task_id,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "report_type": self.report_type,
            "created_at": utc_isoformat(self.created_at),
            "started_at": utc_isoformat(self.started_at),
            "completed_at": utc_isoformat(self.completed_at),
            "error": self.error,
            "original_query": self.original_query,
            "selection_source": self.selection_source,
            "owner_uid": self.owner_uid,
        }

    def to_storage_dict(self) -> Dict[str, Any]:
        data = self.to_dict()
        data["result"] = self.result
        data["task_type"] = self.task_type
        data["source"] = self.source
        data["dedupe_key"] = self.dedupe_key
        return data

    def copy(self) -> "TaskInfo":
        return TaskInfo(**self.__dict__)


class DuplicateTaskError(Exception):
    """Raised when an in-flight database task has the same dedupe key."""

    def __init__(self, stock_code: str, existing_task_id: str):
        self.stock_code = stock_code
        self.existing_task_id = existing_task_id
        super().__init__(f"股票 {stock_code} 正在分析中 (task_id: {existing_task_id})")


class AnalysisTaskQueue:
    """Celery task submission facade preserving the old API-facing contract."""

    _instance: Optional["AnalysisTaskQueue"] = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, max_workers: int = 3, repository: Optional[TaskRecordRepository] = None):
        if hasattr(self, "_initialized") and self._initialized:
            if repository is not None:
                self._repository = repository
            return
        self._max_workers = max(1, int(max_workers))
        self._repository = repository
        self._initialized = True
        logger.info("[TaskQueue] Celery submission service initialized")

    def _repo(self) -> TaskRecordRepository:
        if self._repository is None:
            self._repository = TaskRecordRepository()
        return self._repository

    @property
    def max_workers(self) -> int:
        return self._max_workers

    def sync_max_workers(
        self,
        max_workers: int,
        *,
        log: bool = True,
    ) -> Literal["applied", "unchanged", "deferred_busy"]:
        try:
            target = max(1, int(max_workers))
        except (TypeError, ValueError):
            if log:
                logger.warning("[TaskQueue] 忽略非法 MAX_WORKERS 值: %r", max_workers)
            return "unchanged"
        if target == self._max_workers:
            return "unchanged"
        self._max_workers = target
        return "applied"

    def validate_selection_source(self, selection_source: Optional[str]) -> None:
        if selection_source is not None and selection_source not in SELECTION_SOURCES:
            raise ValueError(f"Invalid selection_source: {selection_source}. Must be one of {SELECTION_SOURCES}")

    def is_analyzing(self, stock_code: str) -> bool:
        return self.get_analyzing_task_id(stock_code) is not None

    def get_analyzing_task_id(self, stock_code: str) -> Optional[str]:
        record = self._repo().get_active_by_dedupe_key(_dedupe_key_for_task("stock_analysis", stock_code))
        return record.task_id if record else None

    def submit_task(
        self,
        stock_code: str,
        stock_name: Optional[str] = None,
        original_query: Optional[str] = None,
        selection_source: Optional[str] = None,
        report_type: str = "detailed",
        force_refresh: bool = False,
        owner_uid: Optional[int] = None,
    ) -> TaskInfo:
        accepted, duplicates = self.submit_tasks_batch(
            [stock_code],
            stock_name=stock_name,
            original_query=original_query,
            selection_source=selection_source,
            report_type=report_type,
            force_refresh=force_refresh,
            owner_uid=owner_uid,
        )
        if duplicates:
            raise duplicates[0]
        if not accepted:
            raise ValueError("股票代码不能为空或仅包含空白字符")
        return accepted[0]

    def submit_tasks_batch(
        self,
        stock_codes: List[str],
        stock_name: Optional[str] = None,
        original_query: Optional[str] = None,
        selection_source: Optional[str] = None,
        report_type: str = "detailed",
        force_refresh: bool = False,
        notify: bool = True,
        owner_uid: Optional[int] = None,
    ) -> Tuple[List[TaskInfo], List[DuplicateTaskError]]:
        self.validate_selection_source(selection_source)
        accepted: List[TaskInfo] = []
        duplicates: List[DuplicateTaskError] = []

        from finance_analysis.tasks.celery.jobs.analysis import run_stock_analysis

        for raw_code in stock_codes:
            stock_code = canonical_stock_code(raw_code)
            if not stock_code:
                continue

            task_id = uuid.uuid4().hex
            payload = {
                "stock_code": stock_code,
                "report_type": report_type,
                "force_refresh": force_refresh,
                "notify": notify,
                "original_query": original_query,
                "selection_source": selection_source,
            }
            task = TaskInfo(
                task_id=task_id,
                stock_code=stock_code,
                stock_name=stock_name,
                status=TaskStatus.PENDING,
                message="任务已加入队列",
                report_type=report_type,
                original_query=original_query,
                selection_source=selection_source,
                owner_uid=owner_uid,
                task_type="stock_analysis",
                source="celery_manual",
                trigger_source="api",
                dedupe_key=_dedupe_key_for_task("stock_analysis", stock_code),
            )
            created = self._create_pending_record(task, payload)
            if not created:
                existing_task_id = task.task_id
                duplicates.append(DuplicateTaskError(stock_code, existing_task_id))
                continue

            try:
                self._apply_celery_task(
                    run_stock_analysis,
                    task_id=task_id,
                    kwargs={
                        "task_id": task_id,
                        "stock_code": stock_code,
                        "report_type": report_type,
                        "force_refresh": force_refresh,
                        "notify": notify,
                        "owner_uid": owner_uid,
                        "task_source": "api",
                    },
                )
            except Exception:
                self._mark_cancelled_record(task, "Celery 任务提交失败，已取消")
                raise
            accepted.append(task.copy())

        return accepted, duplicates

    def submit_bot_analysis(
        self,
        *,
        stock_code: str,
        report_type: str = "simple",
        bot_message: Optional[Dict[str, Any]] = None,
        save_context_snapshot: Optional[bool] = None,
    ) -> TaskInfo:
        from finance_analysis.tasks.celery.jobs.analysis import run_stock_analysis

        stock_code = canonical_stock_code(stock_code)
        if not stock_code:
            raise ValueError("股票代码不能为空或仅包含空白字符")
        task = TaskInfo(
            task_id=uuid.uuid4().hex,
            stock_code=stock_code,
            status=TaskStatus.PENDING,
            message="Bot 分析任务已加入队列",
            report_type=report_type,
            task_type="stock_analysis",
            source="celery_manual",
            trigger_source="bot",
            dedupe_key=_dedupe_key_for_task("stock_analysis", stock_code),
        )
        if not self._create_pending_record(
            task,
            {"stock_code": stock_code, "report_type": report_type, "task_source": "bot"},
        ):
            raise DuplicateTaskError(stock_code, task.task_id)
        try:
            self._apply_celery_task(
                run_stock_analysis,
                task_id=task.task_id,
                kwargs={
                    "task_id": task.task_id,
                    "stock_code": stock_code,
                    "report_type": report_type,
                    "force_refresh": False,
                    "notify": True,
                    "owner_uid": None,
                    "task_source": "bot",
                    "bot_message": bot_message,
                    "save_context_snapshot": save_context_snapshot,
                },
            )
        except Exception:
            self._mark_cancelled_record(task, "Celery 任务提交失败，已取消")
            raise
        return task.copy()

    def submit_market_review(
        self,
        *,
        send_notification: bool,
        override_region: Optional[str] = None,
        bot_message: Optional[Dict[str, Any]] = None,
    ) -> TaskInfo:
        from finance_analysis.tasks.celery.jobs.analysis import run_market_review

        task = TaskInfo(
            task_id=uuid.uuid4().hex,
            stock_code="market_review",
            stock_name="大盘复盘",
            status=TaskStatus.PENDING,
            message="大盘复盘任务已提交",
            report_type="detailed",
            task_type="market_review",
            source="celery_manual",
            trigger_source="bot" if bot_message else "api",
            dedupe_key=_dedupe_key_for_task("market_review", "market_review"),
        )
        if not self._create_pending_record(
            task,
            {"send_notification": send_notification, "override_region": override_region},
        ):
            raise DuplicateTaskError("market_review", task.task_id)
        try:
            self._apply_celery_task(
                run_market_review,
                task_id=task.task_id,
                kwargs={
                    "task_id": task.task_id,
                    "send_notification": send_notification,
                    "override_region": override_region,
                    "bot_message": bot_message,
                },
            )
        except Exception:
            self._mark_cancelled_record(task, "Celery 任务提交失败，已取消")
            raise
        return task.copy()

    def submit_bot_batch_analysis(
        self,
        *,
        stock_codes: List[str],
        bot_message: Optional[Dict[str, Any]] = None,
    ) -> TaskInfo:
        from finance_analysis.tasks.celery.jobs.analysis import run_batch_analysis

        task = TaskInfo(
            task_id=uuid.uuid4().hex,
            stock_code="batch_analysis",
            stock_name=f"批量分析 {len(stock_codes)} 只",
            status=TaskStatus.PENDING,
            message="Bot 批量分析任务已加入队列",
            report_type="simple",
            task_type="batch_analysis",
            source="celery_manual",
            trigger_source="bot",
            dedupe_key=_dedupe_key_for_task("batch_analysis", "batch_analysis"),
        )
        if not self._create_pending_record(task, {"stock_codes": stock_codes, "task_source": "bot"}):
            raise DuplicateTaskError("batch_analysis", task.task_id)
        try:
            self._apply_celery_task(
                run_batch_analysis,
                task_id=task.task_id,
                kwargs={
                    "task_id": task.task_id,
                    "stock_codes": stock_codes,
                    "bot_message": bot_message,
                },
            )
        except Exception:
            self._mark_cancelled_record(task, "Celery 任务提交失败，已取消")
            raise
        return task.copy()

    def _task_metadata(self, task: TaskInfo) -> TaskLifecycleMetadata:
        return TaskLifecycleMetadata(
            task_type=task.task_type or self._infer_task_type(task.stock_code),
            task_name=task.stock_name or self._infer_task_name(task.stock_code, task.task_type or ""),
            source=task.source or "celery_manual",
            uid=task.owner_uid,
            trigger_source=task.trigger_source,
        )

    @staticmethod
    def _infer_task_type(stock_code: str) -> str:
        if stock_code == "market_review":
            return "market_review"
        if stock_code == "batch_analysis":
            return "batch_analysis"
        return "stock_analysis"

    @staticmethod
    def _infer_task_name(stock_code: str, task_type: str) -> str:
        if task_type == "market_review":
            return "大盘复盘"
        if task_type == "batch_analysis":
            return "批量分析"
        return f"股票分析 {stock_code}"

    def _create_pending_record(self, task: TaskInfo, payload: Optional[Dict[str, Any]] = None) -> bool:
        record, created = self._repo().create_pending_or_get_duplicate(
            task_id=task.task_id,
            task_type=task.task_type or self._infer_task_type(task.stock_code),
            task_name=task.stock_name or self._infer_task_name(task.stock_code, task.task_type or ""),
            uid=task.owner_uid,
            source=task.source or "celery_manual",
            trigger_source=task.trigger_source,
            dedupe_key=task.dedupe_key,
            payload=_json_summary(payload, limit=MAX_PAYLOAD_CHARS),
            message=task.message,
            progress=task.progress,
        )
        if not created:
            task.task_id = record.task_id
            task.status = TaskStatus(record.status)
            task.progress = int(record.progress or 0)
            task.message = record.message
        return created

    def _mark_cancelled_record(self, task: TaskInfo, message: str) -> None:
        get_task_lifecycle_service().mark_cancelled(
            task_id=task.task_id,
            metadata=self._task_metadata(task),
            message=message,
        )

    def _apply_celery_task(self, celery_task: Any, *, task_id: str, kwargs: Dict[str, Any]) -> None:
        if os.getenv("PYTEST_CURRENT_TEST") and self._repository is not None:
            return
        celery_task.apply_async(kwargs=kwargs, task_id=task_id)

    def submit_background_task(self, *args: Any, **kwargs: Any) -> TaskInfo:
        raise TypeError("submit_background_task no longer accepts callables; define and submit a Celery task instead")

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        record = self._repo().get_by_task_id(task_id)
        return _task_info_from_record(record) if record else None

    def list_pending_tasks(self) -> List[TaskInfo]:
        return [
            _task_info_from_record(record)
            for record in self._repo().list_tasks(statuses=TaskRecordRepository.ACTIVE_STATUSES, limit=100)
        ]

    def list_all_tasks(self, limit: int = 50) -> List[TaskInfo]:
        return [_task_info_from_record(record) for record in self._repo().list_tasks(limit=limit)]

    def get_task_stats(self) -> Dict[str, int]:
        stats = {"total": self._repo().count_tasks(), "pending": 0, "processing": 0, "completed": 0, "failed": 0}
        stats.update(self._repo().count_by_status())
        return stats

    def update_task_progress(
        self,
        task_id: str,
        progress: int,
        message: Optional[str] = None,
    ) -> Optional[TaskInfo]:
        get_task_lifecycle_service().mark_progress(task_id=task_id, progress=progress, message=message)
        return self.get_task(task_id)

    def mark_task_started(
        self,
        task_id: str,
        message: str = "正在分析中...",
        *,
        task_log: Optional[str] = None,
    ) -> Optional[TaskInfo]:
        task = self.get_task(task_id)
        if task:
            get_task_lifecycle_service().mark_processing(
                task_id=task_id,
                metadata=self._task_metadata(task),
                message=message,
                task_log=task_log,
            )
        return self.get_task(task_id)

    def mark_task_completed(
        self,
        task_id: str,
        result: Optional[Dict[str, Any]],
        *,
        message: str = "分析完成",
        stock_name: Optional[str] = None,
    ) -> Optional[TaskInfo]:
        task = self.get_task(task_id)
        if task:
            if stock_name:
                task.stock_name = stock_name
            get_task_lifecycle_service().mark_completed(
                task_id=task_id,
                metadata=self._task_metadata(task),
                result=result,
                message=message,
            )
        return self.get_task(task_id)

    def mark_task_failed(self, task_id: str, error: str, *, message_prefix: str = "分析失败") -> Optional[TaskInfo]:
        task = self.get_task(task_id)
        if task:
            get_task_lifecycle_service().mark_failed(
                task_id=task_id,
                metadata=self._task_metadata(task),
                error=error,
                message=f"{message_prefix}: {error[:80]}",
            )
        return self.get_task(task_id)

    def shutdown(self) -> None:
        return None


def _task_info_from_record(record: Any) -> TaskInfo:
    from finance_analysis.analysis.context_normalizer import parse_json_field

    payload = parse_json_field(getattr(record, "payload", None)) or {}
    kwargs = payload.get("kwargs") if isinstance(payload, dict) else payload
    if not isinstance(kwargs, dict):
        kwargs = {}
    stock_code = (
        kwargs.get("stock_code")
        or ("market_review" if record.task_type == "market_review" else None)
        or ("batch_analysis" if record.task_type == "batch_analysis" else None)
        or record.task_type
    )
    status = TaskStatus(record.status) if record.status in TaskStatus._value2member_map_ else TaskStatus.PENDING
    return TaskInfo(
        task_id=record.task_id,
        stock_code=str(stock_code),
        stock_name=record.task_name,
        status=status,
        progress=int(record.progress or 0),
        message=record.message,
        result=parse_json_field(getattr(record, "result", None)),
        error=record.error,
        report_type=str(kwargs.get("report_type") or "detailed"),
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.finished_at,
        original_query=kwargs.get("original_query"),
        selection_source=kwargs.get("selection_source"),
        owner_uid=record.uid,
        task_type=record.task_type,
        source=record.source,
        trigger_source=getattr(record, "trigger_source", None),
        dedupe_key=getattr(record, "dedupe_key", None),
    )


def get_task_queue() -> AnalysisTaskQueue:
    queue = AnalysisTaskQueue()
    try:
        from finance_analysis.config.runtime import get_runtime_config

        queue.sync_max_workers(max(1, int(get_runtime_config().max_workers)), log=False)
    except Exception as exc:
        logger.debug("[TaskQueue] 读取 MAX_WORKERS 失败，使用当前并发设置: %s", exc)
    return queue


def reset_task_state_for_tests() -> None:
    """Reset singleton wiring for tests. Task records live in PostgreSQL."""
    AnalysisTaskQueue._instance = None
