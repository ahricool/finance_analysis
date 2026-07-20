"""Lifecycle management for transient Longbridge SDK contexts.

The Python SDK currently does not expose ``close()`` on its synchronous
contexts.  Releasing the last Python reference drops the underlying Rust
context and its background runtime.  Celery workers are long-lived, so every
context created during a task is retained here until ``task_postrun`` and then
released deterministically.

The market streamer does not enter a Celery task scope and is therefore not
registered here; its streaming contexts keep their intended process lifetime.
"""

from __future__ import annotations

import gc
import inspect
import logging
import threading
from contextvars import ContextVar, Token
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_CURRENT_TASK_ID: ContextVar[Optional[str]] = ContextVar("longbridge_celery_task_id", default=None)
_REGISTRY_LOCK = threading.RLock()
_ACTIVE_TASK_IDS: set[str] = set()
_TASK_CONTEXTS: Dict[str, Dict[int, tuple[str, Any]]] = {}


def begin_celery_task_scope(task_id: str) -> Token[Optional[str]]:
    """Start tracking Longbridge contexts created by one Celery task."""
    resolved_task_id = str(task_id)
    token = _CURRENT_TASK_ID.set(resolved_task_id)
    with _REGISTRY_LOCK:
        _ACTIVE_TASK_IDS.add(resolved_task_id)
        _TASK_CONTEXTS.setdefault(resolved_task_id, {})
    return token


def register_task_context(context: Any, *, label: str) -> Any:
    """Register a newly created context when running inside a Celery task.

    Longbridge calls may be made inside a ``ThreadPoolExecutor``. ContextVars
    are not copied to those threads, so the sole active task in the prefork
    worker process is used as a safe fallback. If a non-prefork pool runs
    multiple tasks in one process, ambiguous contexts are left to their
    owner's explicit ``close()`` instead of risking cross-task shutdown.
    """
    if context is None:
        return context

    task_id = _CURRENT_TASK_ID.get()
    with _REGISTRY_LOCK:
        if task_id is None and len(_ACTIVE_TASK_IDS) == 1:
            task_id = next(iter(_ACTIVE_TASK_IDS))
        if task_id is not None and task_id in _ACTIVE_TASK_IDS:
            _TASK_CONTEXTS.setdefault(task_id, {})[id(context)] = (label, context)
    return context


def unregister_task_context(context: Any) -> None:
    """Remove a context that an owner is releasing explicitly."""
    if context is None:
        return
    context_id = id(context)
    with _REGISTRY_LOCK:
        for contexts in _TASK_CONTEXTS.values():
            contexts.pop(context_id, None)


def release_context(context: Any, *, label: str) -> None:
    """Best-effort release across current and future SDK versions."""
    if context is None:
        return

    for method_name in ("close", "disconnect", "shutdown"):
        method = getattr(context, method_name, None)
        if not callable(method):
            continue
        try:
            result = method()
            if inspect.isawaitable(result):
                # Only synchronous contexts are registered by this module.
                result.close()
                logger.warning("[Longbridge] %s.%s() returned an awaitable; reference released", label, method_name)
            else:
                logger.debug("[Longbridge] %s.%s() completed", label, method_name)
        except Exception as exc:
            logger.warning("[Longbridge] releasing %s via %s() failed: %s", label, method_name, exc)
        break


def close_celery_task_scope(task_id: str) -> int:
    """Release every Longbridge context owned by a completed Celery task."""
    resolved_task_id = str(task_id)
    with _REGISTRY_LOCK:
        contexts = list(_TASK_CONTEXTS.pop(resolved_task_id, {}).values())
        _ACTIVE_TASK_IDS.discard(resolved_task_id)

    context_count = len(contexts)
    for label, context in contexts:
        release_context(context, label=label)
    context = None
    if context_count:
        contexts.clear()
        # PyO3 contexts are deallocated by reference release. A collection at
        # the task boundary also handles any Python-side reference cycles.
        gc.collect()
        logger.info("[Longbridge] Celery task %s released %s context(s)", resolved_task_id, context_count)
    return context_count


def end_celery_task_scope(token: Optional[Token[Optional[str]]]) -> None:
    """Restore the ContextVar set by :func:`begin_celery_task_scope`."""
    if token is None:
        return
    try:
        _CURRENT_TASK_ID.reset(token)
    except (LookupError, RuntimeError, ValueError):
        _CURRENT_TASK_ID.set(None)


def close_owned_context(owner: Any, *, label: str, lock: Any = None) -> None:
    """Detach and release ``owner._ctx`` without racing context creation."""
    if lock is None:
        context = getattr(owner, "_ctx", None)
        owner._ctx = None
        owner._config = None
    else:
        with lock:
            context = getattr(owner, "_ctx", None)
            owner._ctx = None
            owner._config = None
    unregister_task_context(context)
    release_context(context, label=label)


__all__ = [
    "begin_celery_task_scope",
    "close_celery_task_scope",
    "close_owned_context",
    "end_celery_task_scope",
    "register_task_context",
    "release_context",
    "unregister_task_context",
]
