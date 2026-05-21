# -*- coding: utf-8 -*-
"""Integration tests for stock-list and watch-list API create responses."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

# Keep this test runnable when optional LLM runtime deps are not installed.
try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

import src.auth as auth
from api.app import create_app
from src.config import Config
from src.storage import DatabaseManager


def _reset_auth_globals() -> None:
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


class StockWatchListApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_auth_globals()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.env_path = self.data_dir / ".env"
        self.db_path = self.data_dir / "stock_watch_api_test.db"
        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519",
                    "GEMINI_API_KEY=test",
                    "ADMIN_AUTH_ENABLED=false",
                    f"DATABASE_PATH={self.db_path}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["DATABASE_PATH"] = str(self.db_path)
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.client = TestClient(create_app(static_dir=self.data_dir / "empty-static"))

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    def test_create_watch_list_item_returns_created_item(self) -> None:
        response = self.client.post(
            "/api/v1/watch-list",
            json={"code": "MU", "name": "MICRON TECHNOLOGY"},
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["code"], "MU")
        self.assertEqual(data["name"], "MICRON TECHNOLOGY")
        self.assertIsInstance(data["id"], int)

    def test_create_stock_holding_returns_created_item(self) -> None:
        response = self.client.post(
            "/api/v1/stock-list",
            json={"code": "MU", "name": "MICRON TECHNOLOGY", "quantity": 10},
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["code"], "MU")
        self.assertEqual(data["name"], "MICRON TECHNOLOGY")
        self.assertEqual(data["quantity"], 10)
        self.assertIsInstance(data["id"], int)


if __name__ == "__main__":
    unittest.main()
