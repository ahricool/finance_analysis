# -*- coding: utf-8 -*-
"""Regression tests for Celery-backed task failure handling."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from finance_analysis.tasks.celery.jobs.analysis import run_stock_analysis
from finance_analysis.tasks.queue import AnalysisTaskQueue, TaskStatus, reset_task_state_for_tests
from tests.task_repo_fakes import FakeTaskRecordRepository


class _FakeLifecycleService:
    def __init__(self, repository: FakeTaskRecordRepository) -> None:
        self.repository = repository

    def mark_processing(self, *, task_id, metadata, payload=None, message=None, progress=10, task_log=None, retry_count=0):
        record = self.repository.get_by_task_id(task_id)
        record.status = "processing"
        record.progress = progress
        record.message = message
        record.started_at = record.started_at or record.updated_at

    def mark_completed(self, *, task_id, metadata, result=None, message=None, progress=100):
        record = self.repository.get_by_task_id(task_id)
        record.status = "completed"
        record.progress = progress
        record.message = message
        record.result = result

    def mark_failed(self, *, task_id, metadata, error, message=None):
        record = self.repository.get_by_task_id(task_id)
        record.status = "failed"
        record.progress = 100
        record.message = message
        record.error = str(error)

    def mark_skipped(self, *, task_id, metadata, message=None, result=None):
        record = self.repository.get_by_task_id(task_id)
        record.status = "skipped"
        record.progress = 100
        record.message = message


class TestCeleryTaskService(unittest.TestCase):
    def setUp(self) -> None:
        reset_task_state_for_tests()

    def tearDown(self) -> None:
        reset_task_state_for_tests()

    def test_run_stock_analysis_marks_failed_for_unsuccessful_result(self):
        repository = FakeTaskRecordRepository()
        queue = AnalysisTaskQueue(max_workers=1, repository=repository)
        accepted, _duplicates = queue.submit_tasks_batch(["600519"], report_type="detailed")

        task = accepted[0]
        with patch(
            "finance_analysis.tasks.celery.jobs.analysis._run_api_stock_analysis",
            side_effect=RuntimeError("JSON 解析失败"),
        ), patch("finance_analysis.tasks.lifecycle.get_task_lifecycle_service", return_value=_FakeLifecycleService(repository)):
            with self.assertRaisesRegex(RuntimeError, "JSON 解析失败"):
                run_stock_analysis(
                    task_id=task.task_id,
                    stock_code="600519",
                    report_type="detailed",
                )

        task_info = queue.get_task(task.task_id)
        self.assertIsNotNone(task_info)
        self.assertEqual(task_info.status, TaskStatus.FAILED)
        self.assertEqual(task_info.error, "JSON 解析失败")
        self.assertIsNone(task_info.result)


if __name__ == "__main__":
    unittest.main()
