# -*- coding: utf-8 -*-
"""Regression tests for Celery-backed task failure handling."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.celery_app.tasks.analysis import run_stock_analysis
from src.tasks.queue import TaskStatus, get_task_queue, reset_task_state_for_tests


class TestCeleryTaskService(unittest.TestCase):
    def setUp(self) -> None:
        reset_task_state_for_tests()

    def tearDown(self) -> None:
        reset_task_state_for_tests()

    def test_run_stock_analysis_marks_failed_for_unsuccessful_result(self):
        queue = get_task_queue()
        with patch.object(run_stock_analysis, "apply_async"):
            accepted, _duplicates = queue.submit_tasks_batch(["600519"], report_type="detailed")

        task = accepted[0]
        with patch(
            "src.celery_app.tasks.analysis._run_api_stock_analysis",
            side_effect=RuntimeError("JSON 解析失败"),
        ):
            result = run_stock_analysis(
                task_id=task.task_id,
                stock_code="600519",
                report_type="detailed",
            )

        self.assertIsNone(result)
        task_info = queue.get_task(task.task_id)
        self.assertIsNotNone(task_info)
        self.assertEqual(task_info.status, TaskStatus.FAILED)
        self.assertEqual(task_info.error, "JSON 解析失败")
        self.assertIsNone(task_info.result)


if __name__ == "__main__":
    unittest.main()
