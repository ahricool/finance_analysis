"""Tests for task-scoped Longbridge SDK context cleanup."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from finance_analysis.integrations.market_data.providers.longbridge.lifecycle import (
    begin_celery_task_scope,
    close_celery_task_scope,
    end_celery_task_scope,
    register_task_context,
)


class _ClosableContext:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def test_celery_task_scope_releases_contexts_created_in_task_threads() -> None:
    token = begin_celery_task_scope("task-threaded")
    main_context = _ClosableContext()
    thread_context = _ClosableContext()
    try:
        register_task_context(main_context, label="ContentContext")
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(register_task_context, thread_context, label="QuoteContext").result()

        assert close_celery_task_scope("task-threaded") == 2
    finally:
        end_celery_task_scope(token)

    assert main_context.close_calls == 1
    assert thread_context.close_calls == 1


def test_context_outside_celery_scope_is_not_closed_by_task_cleanup() -> None:
    context = _ClosableContext()
    register_task_context(context, label="QuoteContext")

    assert close_celery_task_scope("unrelated-task") == 0
    assert context.close_calls == 0


def test_task_cleanup_drops_context_when_sdk_has_no_public_close() -> None:
    dropped: list[bool] = []

    class _DropOnlyContext:
        def __del__(self) -> None:
            dropped.append(True)

    token = begin_celery_task_scope("drop-only-task")
    try:
        context = _DropOnlyContext()
        register_task_context(context, label="QuoteContext")
        del context

        assert close_celery_task_scope("drop-only-task") == 1
    finally:
        end_celery_task_scope(token)

    assert dropped == [True]


def test_celery_signals_close_context_for_tracked_tasks() -> None:
    from finance_analysis.tasks.celery import app as celery_app_module

    context = _ClosableContext()
    task = SimpleNamespace(name="finance_analysis.test")
    with patch.object(celery_app_module, "is_tracked_callable", return_value=True):
        celery_app_module._start_task_file_logging(task_id="signal-task", task=task)
        register_task_context(context, label="ContentContext")
        celery_app_module._stop_task_file_logging(task_id="signal-task", task=task, state="SUCCESS")

    assert context.close_calls == 1
