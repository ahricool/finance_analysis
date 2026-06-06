# -*- coding: utf-8 -*-
"""Unit tests for the always-on Auth status contract."""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from starlette.requests import Request

import src.auth as auth
from api.v1.endpoints.auth import auth_status
from src.config import Config
from src.repositories.user_repo import DEFAULT_ADMIN_EMAIL, UserRepository
from src.storage import DatabaseManager


def _reset_auth_globals() -> None:
    """Reset auth module globals for test isolation."""
    auth._session_secret = None
    auth._rate_limit = {}


def _make_request(*, cookies: dict[str, str] | None = None) -> Request:
    """Create a minimal Starlette request for endpoint unit tests."""
    headers: list[tuple[bytes, bytes]] = []
    if cookies:
        cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
        headers.append((b"cookie", cookie_header.encode("utf-8")))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v1/auth/status",
        "raw_path": b"/api/v1/auth/status",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    return Request(scope)


class AuthStatusSetupStateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_auth_globals()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.env_path = self.data_dir / ".env"
        self.env_path.write_text("STOCK_LIST=600519\n", encoding="utf-8")
        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["SESSION_SECRET"] = "auth-status-test-secret"
        DatabaseManager.reset_instance()
        Config.reset_instance()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("SESSION_SECRET", None)
        _reset_auth_globals()
        self.temp_dir.cleanup()

    def test_status_without_password(self) -> None:
        request = _make_request()
        data = asyncio.run(auth_status(request))
        self.assertEqual(data["setupState"], "enabled")
        self.assertTrue(data["authEnabled"])
        self.assertFalse(data["passwordSet"])

    def test_auth_is_always_enabled(self) -> None:
        self.assertTrue(auth.is_auth_enabled())

    def test_status_password_set_when_db_has_password(self) -> None:
        repo = UserRepository()
        user = repo.get_by_email(DEFAULT_ADMIN_EMAIL)
        self.assertIsNotNone(user)
        repo.set_plain_password(user.uid, "password123")
        request = _make_request()
        data = asyncio.run(auth_status(request))
        self.assertEqual(data["setupState"], "enabled")
        self.assertTrue(data["authEnabled"])
        self.assertTrue(data["passwordSet"])


if __name__ == "__main__":
    unittest.main()
