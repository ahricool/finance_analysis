# -*- coding: utf-8 -*-
"""Integration tests for auth API endpoints (login, logout, change-password, API protection)."""

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.responses import Response
from starlette.requests import Request

# Keep this test runnable when optional LLM runtime deps are not installed.
try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

import src.auth as auth
from api.middlewares.auth import AuthMiddleware
from api.v1.endpoints import auth as auth_endpoint
from src.config import Config


def _reset_auth_globals() -> None:
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


class AuthApiTestCase(unittest.TestCase):
    """Integration tests for /api/v1/auth/* and API protection."""

    def setUp(self) -> None:
        _reset_auth_globals()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.env_path = self.data_dir / ".env"
        self.env_path.write_text(
            "STOCK_LIST=600519\nGEMINI_API_KEY=test\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["DATABASE_PATH"] = str(self.data_dir / "test.db")
        os.environ.pop("AHRI_INITIAL_PASSWORD", None)
        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()
        Config.reset_instance()

        self.data_dir_patcher = patch.object(auth, "_get_data_dir", return_value=self.data_dir)
        self.data_dir_patcher.start()

    def tearDown(self) -> None:
        self.data_dir_patcher.stop()
        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    @staticmethod
    def _build_request(cookies=None):
        return SimpleNamespace(
            headers={},
            url=SimpleNamespace(scheme="http"),
            cookies=cookies or {},
            client=SimpleNamespace(host="127.0.0.1"),
        )

    def test_auth_status_when_password_not_set(self) -> None:
        data = asyncio.run(auth_endpoint.auth_status(self._build_request()))
        self.assertTrue(data["authEnabled"])
        self.assertFalse(data["passwordSet"])
        self.assertFalse(data["loggedIn"])

    def test_login_first_time_set_initial_password(self) -> None:
        response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(email="ahri@localhost", password="newpass123", passwordConfirm="newpass123"),
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("fa_session=", response.headers["set-cookie"])
        self.assertIn(b'"ok":true', response.body)

    def test_login_first_time_mismatch_rejected(self) -> None:
        response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(email="ahri@localhost", password="pass1", passwordConfirm="pass2"),
            )
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'"error":"password_mismatch"', response.body)

    def test_login_after_set_normal_login(self) -> None:
        first_response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(email="ahri@localhost", password="mypass456", passwordConfirm="mypass456"),
            )
        )
        self.assertEqual(first_response.status_code, 200)

        response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(email="ahri@localhost", password="mypass456"),
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"ok":true', response.body)

    def test_login_wrong_password_returns_401(self) -> None:
        first_response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(email="ahri@localhost", password="correct", passwordConfirm="correct"),
            )
        )
        self.assertEqual(first_response.status_code, 200)

        response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(email="ahri@localhost", password="wrong"),
            )
        )
        self.assertEqual(response.status_code, 401)

    def test_logout_clears_cookie(self) -> None:
        response = asyncio.run(auth_endpoint.auth_logout(self._build_request()))
        self.assertEqual(response.status_code, 204)
        self.assertIn("fa_session=", response.headers["set-cookie"])

    def test_logout_invalidates_existing_session(self) -> None:
        login_response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(email="ahri@localhost", password="passwd6", passwordConfirm="passwd6"),
            )
        )
        self.assertEqual(login_response.status_code, 200)
        cookie_header = login_response.headers["set-cookie"]
        session_cookie = cookie_header.split("fa_session=", 1)[1].split(";", 1)[0]
        self.assertTrue(auth.verify_session(session_cookie))

        logout_response = asyncio.run(auth_endpoint.auth_logout(self._build_request()))

        self.assertEqual(logout_response.status_code, 204)
        self.assertFalse(auth.verify_session(session_cookie))

    def test_logout_returns_500_when_session_invalidation_fails(self) -> None:
        with patch.object(auth_endpoint, "rotate_session_secret", return_value=False):
            response = asyncio.run(auth_endpoint.auth_logout(self._build_request()))

        self.assertEqual(response.status_code, 500)
        self.assertIn(b'"error":"internal_error"', response.body)

    def test_change_password_requires_session(self) -> None:
        first_response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(email="ahri@localhost", password="oldpass6", passwordConfirm="oldpass6"),
            )
        )
        self.assertEqual(first_response.status_code, 200)

        response = asyncio.run(
            auth_endpoint.auth_change_password(
                auth_endpoint.ChangePasswordRequest(
                    currentPassword="oldpass6",
                    newPassword="newpass6",
                    newPasswordConfirm="newpass6",
                )
            )
        )
        self.assertIn(response.status_code, (200, 204))

    def test_change_password_wrong_current_rejected(self) -> None:
        first_response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(email="ahri@localhost", password="actual6", passwordConfirm="actual6"),
            )
        )
        self.assertEqual(first_response.status_code, 200)

        response = asyncio.run(
            auth_endpoint.auth_change_password(
                auth_endpoint.ChangePasswordRequest(
                    currentPassword="wrong",
                    newPassword="new123",
                    newPasswordConfirm="new123",
                )
            )
        )
        self.assertEqual(response.status_code, 400)

    def test_protected_api_returns_401_without_session(self) -> None:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/system/config",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "root_path": "",
        }
        request = Request(scope)
        middleware = AuthMiddleware(app=MagicMock())

        response = asyncio.run(middleware.dispatch(request, AsyncMock(return_value=Response(status_code=200))))

        self.assertEqual(response.status_code, 401)

    def test_logout_requires_session(self) -> None:
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/logout",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "root_path": "",
        }
        request = Request(scope)
        middleware = AuthMiddleware(app=MagicMock())
        call_next = AsyncMock(return_value=Response(status_code=204))

        response = asyncio.run(middleware.dispatch(request, call_next))

        self.assertEqual(response.status_code, 401)
        call_next.assert_not_awaited()

    def test_protected_api_accessible_with_session(self) -> None:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/system/config",
            "headers": [(b"cookie", b"fa_session=test-session")],
            "query_string": b"",
            "scheme": "http",
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "root_path": "",
        }
        request = Request(scope)
        middleware = AuthMiddleware(app=MagicMock())
        next_response = Response(status_code=200)
        call_next = AsyncMock(return_value=next_response)

        with patch("api.middlewares.auth.parse_session_user_uid", return_value="test-uid"):
            with patch("api.middlewares.auth.UserRepository") as repo_cls:
                repo_cls.return_value.get_by_uid.return_value = SimpleNamespace(uid="test-uid")
                response = asyncio.run(middleware.dispatch(request, call_next))

        self.assertEqual(response.status_code, 200)
        call_next.assert_awaited_once()

    def test_protected_api_rejects_session_for_missing_user(self) -> None:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/system/config",
            "headers": [(b"cookie", b"fa_session=test-session")],
            "query_string": b"",
            "scheme": "http",
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "root_path": "",
        }
        request = Request(scope)
        middleware = AuthMiddleware(app=MagicMock())
        call_next = AsyncMock(return_value=Response(status_code=200))

        with patch("api.middlewares.auth.parse_session_user_uid", return_value="deleted-uid"):
            with patch("api.middlewares.auth.UserRepository") as repo_cls:
                repo_cls.return_value.get_by_uid.return_value = None
                response = asyncio.run(middleware.dispatch(request, call_next))

        self.assertEqual(response.status_code, 401)
        call_next.assert_not_awaited()

    def test_database_manager_is_usable_during_default_admin_bootstrap(self) -> None:
        from src.storage import DatabaseManager

        seen = {}

        class BootstrapRepo:
            def __init__(self, db):
                seen["initialized_during_bootstrap"] = getattr(db, "_initialized", False)

            def ensure_default_admin(self):
                return "default-user-uid"

        fake_config = SimpleNamespace(
            get_db_url=lambda: "postgresql+psycopg2://user:pass@127.0.0.1:5432/db",
            db_pool_size=1,
            db_max_overflow=0,
            db_pool_recycle=1800,
        )

        DatabaseManager.reset_instance()
        with patch("src.storage.get_config", return_value=fake_config):
            with patch("src.storage.create_engine", return_value=object()):
                with patch("src.storage.sessionmaker", return_value=lambda: object()):
                    with patch("src.db_migrations.run_alembic_upgrade_head"):
                        with patch("src.repositories.user_repo.UserRepository", side_effect=BootstrapRepo):
                            with patch("src.db_schema.run_user_scoped_migrations"):
                                db = DatabaseManager.get_instance()

        self.assertTrue(seen["initialized_during_bootstrap"])
        self.assertTrue(getattr(db, "_initialized", False))
        DatabaseManager.reset_instance()

    def test_auth_settings_requires_session(self) -> None:
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/settings",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "root_path": "",
        }
        request = Request(scope)
        middleware = AuthMiddleware(app=MagicMock())

        response = asyncio.run(middleware.dispatch(request, AsyncMock(return_value=Response(status_code=200))))

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
