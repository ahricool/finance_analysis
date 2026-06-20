# -*- coding: utf-8 -*-
"""Tests for unified task lifecycle tracking."""

from __future__ import annotations

import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tasks.lifecycle import _json_summary, TaskSkipped, track_task
from src.tasks.queue import AnalysisTaskQueue, reset_task_state_for_tests
from tests.task_repo_fakes import FakeTaskRecordRepository


class _RecordingLifecycleService:
    def __init__(self) -> None:
        self.events = []

    def create_pending(self, **kwargs):
        self.events.append(("pending", kwargs))

    def mark_processing(self, **kwargs):
        self.events.append(("processing", kwargs))

    def mark_progress(self, **kwargs):
        self.events.append(("progress", kwargs))

    def mark_completed(self, **kwargs):
        self.events.append(("completed", kwargs))

    def mark_skipped(self, **kwargs):
        self.events.append(("skipped", kwargs))

    def mark_cancelled(self, **kwargs):
        self.events.append(("cancelled", kwargs))

    def mark_failed(self, **kwargs):
        self.events.append(("failed", kwargs))


class TaskLifecycleDecoratorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["LOG_DIR"] = str(Path(self.temp_dir.name) / "logs")

    def tearDown(self) -> None:
        os.environ.pop("LOG_DIR", None)
        self.temp_dir.cleanup()

    def test_decorator_preserves_return_value_and_records_completed(self) -> None:
        service = _RecordingLifecycleService()

        @track_task(task_type="unit", task_name="Unit Task", source="apscheduler")
        def run(value: int) -> int:
            return value + 1

        with patch("src.tasks.lifecycle.get_task_lifecycle_service", return_value=service):
            self.assertEqual(run(2), 3)

        self.assertEqual([event[0] for event in service.events], ["processing", "completed"])
        self.assertEqual(service.events[0][1]["task_id"], service.events[1][1]["task_id"])
        self.assertIn(service.events[0][1]["task_id"], service.events[0][1]["task_log"])

    def test_decorator_reraises_original_exception_and_records_failed(self) -> None:
        service = _RecordingLifecycleService()

        @track_task(task_type="unit", task_name="Unit Task", source="apscheduler")
        def run() -> None:
            raise RuntimeError("boom")

        with patch("src.tasks.lifecycle.get_task_lifecycle_service", return_value=service):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                run()

        self.assertEqual([event[0] for event in service.events], ["processing", "failed"])
        self.assertIsInstance(service.events[-1][1]["error"], RuntimeError)

    def test_decorator_sends_system_error_notification_on_failure(self) -> None:
        service = _RecordingLifecycleService()

        @track_task(
            task_type="unit",
            task_name="Unit Task",
            source="apscheduler",
            task_id_getter=lambda: "task-123",
        )
        def run() -> None:
            raise RuntimeError("api_key=super-secret failed")

        with patch("src.tasks.lifecycle.get_task_lifecycle_service", return_value=service), \
             patch("src.notification.NotificationService") as notification_service:
            notification_service.return_value.send.return_value = True
            with self.assertRaisesRegex(RuntimeError, "failed"):
                run()

        notification_service.return_value.send.assert_called_once()
        content = notification_service.return_value.send.call_args.args[0]
        kwargs = notification_service.return_value.send.call_args.kwargs
        self.assertIn("任务失败通知", content)
        self.assertIn("Unit Task", content)
        self.assertIn("RuntimeError", content)
        self.assertIn("调用栈", content)
        self.assertIn("api_key=***", content)
        self.assertNotIn("super-secret", content)
        self.assertEqual(kwargs["route_type"], "system_error")
        self.assertEqual(kwargs["severity"], "error")
        self.assertEqual(kwargs["dedup_key"], "task_failure:task-123")
        self.assertEqual(kwargs["cooldown_key"], "task_failure:task-123")

    def test_notification_failure_does_not_replace_task_exception(self) -> None:
        service = _RecordingLifecycleService()

        @track_task(task_type="unit", task_name="Unit Task", source="apscheduler")
        def run() -> None:
            raise RuntimeError("boom")

        with patch("src.tasks.lifecycle.get_task_lifecycle_service", return_value=service), \
             patch("src.notification.NotificationService") as notification_service:
            notification_service.return_value.send.side_effect = RuntimeError("notify down")
            with self.assertRaisesRegex(RuntimeError, "boom"):
                run()

        self.assertEqual([event[0] for event in service.events], ["processing", "failed"])

    def test_scheduler_style_runs_get_distinct_task_ids(self) -> None:
        service = _RecordingLifecycleService()

        @track_task(task_type="unit", task_name="Unit Task", source="apscheduler")
        def run() -> str:
            return "ok"

        with patch("src.tasks.lifecycle.get_task_lifecycle_service", return_value=service):
            run()
            run()

        processing_ids = [event[1]["task_id"] for event in service.events if event[0] == "processing"]
        self.assertEqual(len(processing_ids), 2)
        self.assertNotEqual(processing_ids[0], processing_ids[1])

    def test_task_skipped_records_skipped_without_failure(self) -> None:
        service = _RecordingLifecycleService()

        @track_task(task_type="unit", task_name="Unit Task", source="apscheduler")
        def run() -> None:
            raise TaskSkipped("no work")

        with patch("src.tasks.lifecycle.get_task_lifecycle_service", return_value=service):
            self.assertIsNone(run())

        self.assertEqual([event[0] for event in service.events], ["processing", "skipped"])

    def test_json_summary_is_valid_json_after_truncation_and_redaction(self) -> None:
        summary = _json_summary(
            {
                "api_key": "secret-value",
                "items": [{"text": "x" * 5000} for _ in range(10)],
            },
            limit=800,
        )

        parsed = json.loads(summary or "")
        self.assertIsInstance(parsed, dict)
        self.assertTrue(parsed.get("truncated"))
        self.assertIn("***", parsed.get("preview", ""))
        self.assertNotIn("secret-value", summary or "")


class TaskQueueLifecycleIntegrationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        reset_task_state_for_tests()

    def tearDown(self) -> None:
        reset_task_state_for_tests()

    def test_submit_creates_pending_record_with_same_task_id_as_redis_state(self) -> None:
        repository = FakeTaskRecordRepository()
        queue = AnalysisTaskQueue(max_workers=1, repository=repository)

        from src.celery_app.tasks.analysis import run_stock_analysis

        with patch.object(run_stock_analysis, "apply_async"):
            accepted, duplicates = queue.submit_tasks_batch(["600519"], report_type="detailed")

        self.assertEqual(duplicates, [])
        task = accepted[0]
        self.assertEqual(queue.get_task(task.task_id).task_id, task.task_id)
        self.assertEqual(repository.get_by_task_id(task.task_id).status, "pending")


if __name__ == "__main__":
    unittest.main()
