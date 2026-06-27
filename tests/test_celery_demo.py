# -*- coding: utf-8 -*-
"""Tests for Celery demo task and API endpoint."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from finance_analysis.interfaces.api.v1.endpoints.celery_demo import submit_add_task
from finance_analysis.interfaces.api.v1.schemas.celery_demo import CeleryAddRequest
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.jobs.demo_add.tasks import add

class CeleryDemoTaskTestCase(unittest.TestCase):
    """Unit tests for the demo add Celery task."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_path = Path(self.temp_dir.name) / ".env"
        self.env_path.write_text("GEMINI_API_KEY=test\n", encoding="utf-8")
        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["DATA_DIR"] = str(Path(self.temp_dir.name) / "data")
        from finance_analysis.core.paths import clear_paths_cache

        clear_paths_cache()

        self._original_always_eager = celery_app.conf.task_always_eager
        celery_app.conf.task_always_eager = True

    def tearDown(self) -> None:
        celery_app.conf.task_always_eager = self._original_always_eager
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATA_DIR", None)
        from finance_analysis.core.paths import clear_paths_cache

        clear_paths_cache()
        self.temp_dir.cleanup()

    def test_add_task_returns_sum(self) -> None:
        result = add.delay(2, 3)
        self.assertTrue(result.successful())
        self.assertEqual(result.get(), 5)

    def test_add_task_handles_floats(self) -> None:
        result = add.delay(1.5, 2.25)
        self.assertEqual(result.get(), 3.75)


class CeleryDemoEndpointTestCase(unittest.TestCase):
    """Endpoint tests for submit_add_task."""

    def test_submit_add_task_returns_success_without_waiting(self) -> None:
        with patch("finance_analysis.interfaces.api.v1.endpoints.celery_demo.add.delay") as mock_delay:
            mock_delay.return_value = MagicMock(id="task-123")

            response = submit_add_task(CeleryAddRequest(x=4, y=6))

        self.assertTrue(response.success)
        self.assertEqual(response.message, "Task submitted")
        mock_delay.assert_called_once_with(4, 6)
