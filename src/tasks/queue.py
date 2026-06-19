# -*- coding: utf-8 -*-
"""Celery-backed task submission and task-state compatibility layer."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Literal, Optional, Tuple

from data_provider.base import canonical_stock_code, normalize_stock_code
from src.time_utils import utc_isoformat
from src.utils.analysis_metadata import SELECTION_SOURCES

logger = logging.getLogger(__name__)

TASK_EVENT_CHANNEL = "finance_analysis:tasks:events"
TASK_INFO_PREFIX = "finance_analysis:tasks:info:"
TASK_INDEX_KEY = "finance_analysis:tasks:index"
TASK_ANALYZING_KEY = "finance_analysis:tasks:analyzing"
TASK_TTL_SECONDS = 7 * 24 * 60 * 60


def _dedupe_stock_code_key(stock_code: str) -> str:
    """Normalize equivalent stock-code shapes to one duplicate-detection key."""
    return canonical_stock_code(normalize_stock_code(stock_code))


def _datetime_to_iso(value: Optional[datetime]) -> Optional[str]:
    return utc_isoformat(value)


def _datetime_from_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class TaskStatus(str, Enum):
    """Task status enumeration."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskInfo:
    """Task information used by API responses and SSE events."""

    task_id: str
    stock_code: str
    stock_name: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    report_type: str = "detailed"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    original_query: Optional[str] = None
    selection_source: Optional[str] = None
    owner_uid: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "report_type": self.report_type,
            "created_at": _datetime_to_iso(self.created_at),
            "started_at": _datetime_to_iso(self.started_at),
            "completed_at": _datetime_to_iso(self.completed_at),
            "error": self.error,
            "original_query": self.original_query,
            "selection_source": self.selection_source,
            "owner_uid": self.owner_uid,
        }

    def to_storage_dict(self) -> Dict[str, Any]:
        data = self.to_dict()
        data["result"] = self.result
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskInfo":
        return cls(
            task_id=str(data["task_id"]),
            stock_code=str(data.get("stock_code") or ""),
            stock_name=data.get("stock_name"),
            status=TaskStatus(data.get("status") or TaskStatus.PENDING.value),
            progress=int(data.get("progress") or 0),
            message=data.get("message"),
            result=data.get("result"),
            error=data.get("error"),
            report_type=data.get("report_type") or "detailed",
            created_at=_datetime_from_iso(data.get("created_at")) or datetime.now(timezone.utc),
            started_at=_datetime_from_iso(data.get("started_at")),
            completed_at=_datetime_from_iso(data.get("completed_at")),
            original_query=data.get("original_query"),
            selection_source=data.get("selection_source"),
            owner_uid=data.get("owner_uid"),
        )

    def copy(self) -> "TaskInfo":
        return TaskInfo.from_dict(self.to_storage_dict())


class DuplicateTaskError(Exception):
    """Raised when the same stock already has an in-flight task."""

    def __init__(self, stock_code: str, existing_task_id: str):
        self.stock_code = stock_code
        self.existing_task_id = existing_task_id
        super().__init__(f"股票 {stock_code} 正在分析中 (task_id: {existing_task_id})")


class _TaskStateStore:
    """Redis-backed task state with an in-memory fallback for tests/dev."""

    def __init__(self) -> None:
        self._redis = None
        self._redis_failed = False
        self._memory_tasks: Dict[str, TaskInfo] = {}
        self._memory_analyzing: Dict[str, str] = {}
        self._memory_subscribers: List[asyncio.Queue] = []
        self._lock = threading.RLock()

    def _get_redis(self):
        if self._redis_failed:
            return None
        if self._redis is not None:
            return self._redis
        try:
            import redis
            from src.config import get_config

            client = redis.Redis.from_url(get_config().redis_url, decode_responses=True)
            client.ping()
            self._redis = client
            return client
        except Exception as exc:
            self._redis_failed = True
            logger.debug("Task state Redis unavailable; using in-memory fallback: %s", exc)
            return None

    @property
    def uses_redis(self) -> bool:
        return self._get_redis() is not None

    def reset_memory(self) -> None:
        with self._lock:
            self._memory_tasks.clear()
            self._memory_analyzing.clear()
            self._memory_subscribers.clear()
            self._redis_failed = True
            self._redis = None

    def create_task(self, task: TaskInfo) -> bool:
        dedupe_key = _dedupe_stock_code_key(task.stock_code)
        redis_client = self._get_redis()
        if redis_client is not None:
            if not redis_client.hsetnx(TASK_ANALYZING_KEY, dedupe_key, task.task_id):
                return False
            pipe = redis_client.pipeline()
            pipe.setex(f"{TASK_INFO_PREFIX}{task.task_id}", TASK_TTL_SECONDS, json.dumps(task.to_storage_dict()))
            pipe.zadd(TASK_INDEX_KEY, {task.task_id: task.created_at.timestamp()})
            pipe.expire(TASK_INDEX_KEY, TASK_TTL_SECONDS)
            pipe.execute()
            return True

        with self._lock:
            if dedupe_key in self._memory_analyzing:
                return False
            self._memory_analyzing[dedupe_key] = task.task_id
            self._memory_tasks[task.task_id] = task.copy()
            return True

    def remove_task(self, task_id: str) -> None:
        task = self.get_task(task_id)
        redis_client = self._get_redis()
        if redis_client is not None:
            pipe = redis_client.pipeline()
            pipe.delete(f"{TASK_INFO_PREFIX}{task_id}")
            pipe.zrem(TASK_INDEX_KEY, task_id)
            if task:
                pipe.hdel(TASK_ANALYZING_KEY, _dedupe_stock_code_key(task.stock_code))
            pipe.execute()
            return

        with self._lock:
            removed = self._memory_tasks.pop(task_id, None)
            if removed:
                self._memory_analyzing.pop(_dedupe_stock_code_key(removed.stock_code), None)

    def get_analyzing_task_id(self, stock_code: str) -> Optional[str]:
        dedupe_key = _dedupe_stock_code_key(stock_code)
        redis_client = self._get_redis()
        if redis_client is not None:
            task_id = redis_client.hget(TASK_ANALYZING_KEY, dedupe_key)
            return str(task_id) if task_id else None

        with self._lock:
            return self._memory_analyzing.get(dedupe_key)

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        redis_client = self._get_redis()
        if redis_client is not None:
            raw = redis_client.get(f"{TASK_INFO_PREFIX}{task_id}")
            if not raw:
                return None
            try:
                return TaskInfo.from_dict(json.loads(raw))
            except Exception:
                logger.warning("Invalid task state payload ignored: task_id=%s", task_id)
                return None

        with self._lock:
            task = self._memory_tasks.get(task_id)
            return task.copy() if task else None

    def list_tasks(self, limit: int = 50) -> List[TaskInfo]:
        redis_client = self._get_redis()
        if redis_client is not None:
            task_ids = redis_client.zrevrange(TASK_INDEX_KEY, 0, max(0, limit - 1))
            tasks = [self.get_task(str(task_id)) for task_id in task_ids]
            return [task for task in tasks if task is not None]

        with self._lock:
            return [
                task.copy()
                for task in sorted(self._memory_tasks.values(), key=lambda t: t.created_at, reverse=True)[:limit]
            ]

    def update_task(self, task_id: str, **updates: Any) -> Optional[TaskInfo]:
        task = self.get_task(task_id)
        if not task:
            return None

        for key, value in updates.items():
            if key == "status" and isinstance(value, str):
                value = TaskStatus(value)
            setattr(task, key, value)

        redis_client = self._get_redis()
        if redis_client is not None:
            pipe = redis_client.pipeline()
            pipe.setex(f"{TASK_INFO_PREFIX}{task.task_id}", TASK_TTL_SECONDS, json.dumps(task.to_storage_dict()))
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                pipe.hdel(TASK_ANALYZING_KEY, _dedupe_stock_code_key(task.stock_code))
            pipe.execute()
        else:
            with self._lock:
                self._memory_tasks[task.task_id] = task.copy()
                if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    self._memory_analyzing.pop(_dedupe_stock_code_key(task.stock_code), None)

        return task.copy()

    def publish(self, event_type: str, task: TaskInfo | Dict[str, Any]) -> None:
        data = task.to_dict() if isinstance(task, TaskInfo) else task
        event = {"type": event_type, "data": data}
        redis_client = self._get_redis()
        if redis_client is not None:
            redis_client.publish(TASK_EVENT_CHANNEL, json.dumps(event, ensure_ascii=False))
            return

        with self._lock:
            subscribers = list(self._memory_subscribers)
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except Exception:
                logger.debug("Failed to enqueue in-memory task event", exc_info=True)

    def subscribe_memory(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._memory_subscribers.append(queue)

    def unsubscribe_memory(self, queue: asyncio.Queue) -> None:
        with self._lock:
            if queue in self._memory_subscribers:
                self._memory_subscribers.remove(queue)


_STORE = _TaskStateStore()


class AnalysisTaskQueue:
    """Celery-backed queue preserving the old API-facing task contract."""

    _instance: Optional["AnalysisTaskQueue"] = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, max_workers: int = 3):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._max_workers = max(1, int(max_workers))
        self._store = _STORE
        self._tasks = self._store._memory_tasks
        self._analyzing_stocks = self._store._memory_analyzing
        self._futures: Dict[str, Any] = {}
        self._executor = None
        self._data_lock = self._store._lock
        self._initialized = True
        logger.info("[TaskQueue] Celery-backed task queue initialized")

    @property
    def max_workers(self) -> int:
        return self._max_workers

    def sync_max_workers(self, max_workers: int, *, log: bool = True) -> Literal["applied", "unchanged", "deferred_busy"]:
        try:
            target = max(1, int(max_workers))
        except (TypeError, ValueError):
            if log:
                logger.warning("[TaskQueue] 忽略非法 MAX_WORKERS 值: %r", max_workers)
            return "unchanged"
        if target == self._max_workers:
            return "unchanged"
        if self.list_pending_tasks() or self._analyzing_stocks:
            return "deferred_busy"
        self._max_workers = target
        executor = self._executor
        self._executor = None
        if executor is not None and hasattr(executor, "shutdown"):
            executor.shutdown(wait=False)
        return "applied"

    def validate_selection_source(self, selection_source: Optional[str]) -> None:
        if selection_source is not None and selection_source not in SELECTION_SOURCES:
            raise ValueError(f"Invalid selection_source: {selection_source}. Must be one of {SELECTION_SOURCES}")

    def is_analyzing(self, stock_code: str) -> bool:
        return self.get_analyzing_task_id(stock_code) is not None

    def get_analyzing_task_id(self, stock_code: str) -> Optional[str]:
        return self._store.get_analyzing_task_id(stock_code)

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
        created_task_ids: List[str] = []

        from src.celery_app.tasks.analysis import run_stock_analysis

        for stock_code in [canonical_stock_code(code) for code in stock_codes]:
            if not stock_code:
                continue
            existing_task_id = self.get_analyzing_task_id(stock_code)
            if existing_task_id:
                duplicates.append(DuplicateTaskError(stock_code, existing_task_id))
                continue

            task_id = uuid.uuid4().hex
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
            )
            if not self._store.create_task(task):
                existing_task_id = self.get_analyzing_task_id(stock_code) or ""
                duplicates.append(DuplicateTaskError(stock_code, existing_task_id))
                continue
            created_task_ids.append(task_id)
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
                for created_task_id in created_task_ids:
                    self._store.remove_task(created_task_id)
                raise
            accepted.append(task.copy())
            self._broadcast_event("task_created", task.to_dict())

        return accepted, duplicates

    def submit_bot_analysis(
        self,
        *,
        stock_code: str,
        report_type: str = "simple",
        bot_message: Optional[Dict[str, Any]] = None,
        save_context_snapshot: Optional[bool] = None,
    ) -> TaskInfo:
        from src.celery_app.tasks.analysis import run_stock_analysis

        stock_code = canonical_stock_code(stock_code)
        if not stock_code:
            raise ValueError("股票代码不能为空或仅包含空白字符")
        existing_task_id = self.get_analyzing_task_id(stock_code)
        if existing_task_id:
            raise DuplicateTaskError(stock_code, existing_task_id)

        task_id = uuid.uuid4().hex
        task = TaskInfo(
            task_id=task_id,
            stock_code=stock_code,
            status=TaskStatus.PENDING,
            message="Bot 分析任务已加入队列",
            report_type=report_type,
        )
        if not self._store.create_task(task):
            raise DuplicateTaskError(stock_code, self.get_analyzing_task_id(stock_code) or "")
        try:
            self._apply_celery_task(
                run_stock_analysis,
                task_id=task_id,
                kwargs={
                    "task_id": task_id,
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
            self._store.remove_task(task_id)
            raise
        self._broadcast_event("task_created", task.to_dict())
        return task.copy()

    def submit_market_review(
        self,
        *,
        send_notification: bool,
        override_region: Optional[str] = None,
        bot_message: Optional[Dict[str, Any]] = None,
    ) -> TaskInfo:
        from src.celery_app.tasks.analysis import run_market_review

        task_id = uuid.uuid4().hex
        task = TaskInfo(
            task_id=task_id,
            stock_code="market_review",
            stock_name="大盘复盘",
            status=TaskStatus.PENDING,
            message="大盘复盘任务已提交",
            report_type="detailed",
        )
        if not self._store.create_task(task):
            raise DuplicateTaskError("market_review", self.get_analyzing_task_id("market_review") or "")
        try:
            self._apply_celery_task(
                run_market_review,
                task_id=task_id,
                kwargs={
                    "task_id": task_id,
                    "send_notification": send_notification,
                    "override_region": override_region,
                    "bot_message": bot_message,
                },
            )
        except Exception:
            self._store.remove_task(task_id)
            raise
        self._broadcast_event("task_created", task.to_dict())
        return task.copy()

    def submit_bot_batch_analysis(
        self,
        *,
        stock_codes: List[str],
        bot_message: Optional[Dict[str, Any]] = None,
    ) -> TaskInfo:
        from src.celery_app.tasks.analysis import run_batch_analysis

        task_id = uuid.uuid4().hex
        task = TaskInfo(
            task_id=task_id,
            stock_code="batch_analysis",
            stock_name=f"批量分析 {len(stock_codes)} 只",
            status=TaskStatus.PENDING,
            message="Bot 批量分析任务已加入队列",
            report_type="simple",
        )
        if not self._store.create_task(task):
            raise DuplicateTaskError("batch_analysis", self.get_analyzing_task_id("batch_analysis") or "")
        try:
            self._apply_celery_task(
                run_batch_analysis,
                task_id=task_id,
                kwargs={
                    "task_id": task_id,
                    "stock_codes": stock_codes,
                    "bot_message": bot_message,
                },
            )
        except Exception:
            self._store.remove_task(task_id)
            raise
        self._broadcast_event("task_created", task.to_dict())
        return task.copy()

    def _apply_celery_task(self, celery_task: Any, *, task_id: str, kwargs: Dict[str, Any]) -> None:
        if os.getenv("PYTEST_CURRENT_TEST") and not self._store.uses_redis:
            return
        celery_task.apply_async(kwargs=kwargs, task_id=task_id)

    def submit_background_task(self, *args: Any, **kwargs: Any) -> TaskInfo:
        raise TypeError("submit_background_task no longer accepts callables; define and submit a Celery task instead")

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        return self._store.get_task(task_id)

    def list_pending_tasks(self) -> List[TaskInfo]:
        return [
            task for task in self.list_all_tasks(limit=100)
            if task.status in (TaskStatus.PENDING, TaskStatus.PROCESSING)
        ]

    def list_all_tasks(self, limit: int = 50) -> List[TaskInfo]:
        return self._store.list_tasks(limit=limit)

    def get_task_stats(self) -> Dict[str, int]:
        stats = {"total": 0, "pending": 0, "processing": 0, "completed": 0, "failed": 0}
        for task in self.list_all_tasks(limit=1000):
            stats["total"] += 1
            stats[task.status.value] = stats.get(task.status.value, 0) + 1
        return stats

    def update_task_progress(
        self,
        task_id: str,
        progress: int,
        message: Optional[str] = None,
        *,
        event_type: str = "task_progress",
    ) -> Optional[TaskInfo]:
        task = self.get_task(task_id)
        if not task or task.status not in (TaskStatus.PENDING, TaskStatus.PROCESSING):
            return None
        updates: Dict[str, Any] = {"progress": max(task.progress, max(0, min(99, int(progress))))}
        if message is not None:
            updates["message"] = message
        updated = self._store.update_task(task_id, **updates)
        if updated:
            self._broadcast_event(event_type, updated.to_dict())
        return updated

    def mark_task_started(self, task_id: str, message: str = "正在分析中...") -> Optional[TaskInfo]:
        task = self._store.update_task(
            task_id,
            status=TaskStatus.PROCESSING,
            started_at=datetime.now(timezone.utc),
            progress=10,
            message=message,
        )
        if task:
            self._broadcast_event("task_started", task.to_dict())
        return task

    def mark_task_completed(
        self,
        task_id: str,
        result: Optional[Dict[str, Any]],
        *,
        message: str = "分析完成",
        stock_name: Optional[str] = None,
    ) -> Optional[TaskInfo]:
        task = self._store.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
            progress=100,
            result=result,
            message=message,
            stock_name=stock_name,
        )
        if task:
            self._broadcast_event("task_completed", task.to_dict())
        return task

    def mark_task_failed(self, task_id: str, error: str, *, message_prefix: str = "分析失败") -> Optional[TaskInfo]:
        task = self._store.update_task(
            task_id,
            status=TaskStatus.FAILED,
            completed_at=datetime.now(timezone.utc),
            error=error[:200],
            message=f"{message_prefix}: {error[:80]}",
        )
        if task:
            self._broadcast_event("task_failed", task.to_dict())
        return task

    def _broadcast_event(self, event_type: str, data: Dict[str, Any]) -> None:
        self._store.publish(event_type, data)

    def subscribe(self, queue: asyncio.Queue) -> None:
        self._store.subscribe_memory(queue)

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._store.unsubscribe_memory(queue)

    async def iter_events(self, heartbeat_seconds: float = 30.0) -> AsyncIterator[Dict[str, Any]]:
        if self._store.uses_redis:
            import redis.asyncio as aioredis
            from src.config import get_config

            client = aioredis.Redis.from_url(get_config().redis_url, decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.subscribe(TASK_EVENT_CHANNEL)
            try:
                last_event_at = time.monotonic()
                while True:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message and message.get("data"):
                        last_event_at = time.monotonic()
                        yield json.loads(message["data"])
                    elif time.monotonic() - last_event_at >= heartbeat_seconds:
                        last_event_at = time.monotonic()
                        yield {"type": "heartbeat", "data": {"timestamp": utc_isoformat(datetime.now(timezone.utc))}}
                    await asyncio.sleep(0.05)
            finally:
                await pubsub.unsubscribe(TASK_EVENT_CHANNEL)
                await pubsub.close()
                await client.close()
            return

        event_queue: asyncio.Queue = asyncio.Queue()
        self.subscribe(event_queue)
        try:
            while True:
                try:
                    yield await asyncio.wait_for(event_queue.get(), timeout=heartbeat_seconds)
                except asyncio.TimeoutError:
                    yield {"type": "heartbeat", "data": {"timestamp": utc_isoformat(datetime.now(timezone.utc))}}
        finally:
            self.unsubscribe(event_queue)

    def shutdown(self) -> None:
        """Compatibility no-op; Celery workers own execution lifecycle."""
        return None


def get_task_queue() -> AnalysisTaskQueue:
    queue = AnalysisTaskQueue()
    try:
        from src.config import get_config

        queue.sync_max_workers(max(1, int(getattr(get_config(), "max_workers", queue.max_workers))), log=False)
    except Exception as exc:
        logger.debug("[TaskQueue] 读取 MAX_WORKERS 失败，使用当前并发设置: %s", exc)
    return queue


def reset_task_state_for_tests() -> None:
    """Reset only the in-memory fallback store used by unit tests."""
    _STORE.reset_memory()
    AnalysisTaskQueue._instance = None
