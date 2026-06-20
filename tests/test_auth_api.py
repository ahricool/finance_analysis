# -*- coding: utf-8 -*-
"""Integration tests for auth API endpoints and API protection."""

import asyncio
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image
from fastapi.responses import Response
from starlette.datastructures import Headers
from starlette.datastructures import UploadFile
from starlette.requests import Request

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

import finance_analysis.users.auth as auth
from finance_analysis.interfaces.api.middlewares.auth import AuthMiddleware
from finance_analysis.interfaces.api.v1.endpoints import auth as auth_endpoint
from finance_analysis.config import Config
from finance_analysis.database.repositories.user import DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_USERNAME


def _reset_auth_globals() -> None:
    auth._secret_key = None
    auth._rate_limit = {}


class FakeUser:
    def __init__(self, uid: int, email: str, username: str, password: str | None = None):
        self.id = uid
        self.email = email
        self.username = username
        self.password_hash = password
        self.avatar_url = None
        self.role = "admin"
        self.extra = {}


class FakeUserRepository:
    users: dict[str, FakeUser] = {}

    def get_by_uid(self, uid: int):
        return next((user for user in self.users.values() if user.id == uid), None)

    def get_by_email(self, email: str):
        return self.users.get((email or "").strip().lower())

    def user_needs_password_setup(self, email: str):
        user = self.get_by_email(email)
        if user is None:
            return None
        return not bool(user.password_hash)

    def set_plain_password(self, uid: int, plain: str) -> None:
        user = self.get_by_uid(uid)
        if user is not None:
            user.password_hash = plain

    def verify_credentials(self, email: str, password: str):
        user = self.get_by_email(email)
        if user is not None and user.password_hash == password:
            return user
        return None

    def verify_plain_for_uid(self, uid: int, plain: str) -> bool:
        user = self.get_by_uid(uid)
        return user is not None and user.password_hash == plain

    def update_profile(self, uid: int, *, username=None, gender=None, notification=None):
        user = self.get_by_uid(uid)
        if user is None:
            return None
        if username is not None:
            user.username = username
        extra = self._normalized_extra(user.extra)
        if gender is not None:
            extra["gender"] = gender
        if notification is not None:
            extra["notification"] = notification
        user.extra = extra
        return user

    def set_avatar_url(self, uid: int, avatar_url: str):
        user = self.get_by_uid(uid)
        if user is None:
            return None
        user.avatar_url = avatar_url
        return user

    def any_user_has_password(self) -> bool:
        return any(bool(user.password_hash) for user in self.users.values())

    @staticmethod
    def _normalized_extra(extra):
        notification = (extra or {}).get("notification") if isinstance(extra, dict) else None
        if not isinstance(notification, dict):
            notification = {}
        return {
            "gender": (extra or {}).get("gender", "unknown") if isinstance(extra, dict) else "unknown",
            "notification": {
                "ntfy": notification.get("ntfy") or [{"url": ""}],
                "telegram": notification.get("telegram") or [{"bot_token": "", "chat_id": ""}],
            },
        }

    def to_public_dict(self, user: FakeUser):
        return {
            "uid": user.id,
            "username": user.username,
            "email": user.email,
            "avatarUrl": user.avatar_url,
            "role": user.role,
            "extra": {
                "gender": self._normalized_extra(user.extra)["gender"],
            },
        }

    def to_profile_dict(self, user: FakeUser):
        payload = self.to_public_dict(user)
        payload["extra"] = self._normalized_extra(user.extra)
        return payload


class AuthApiTestCase(unittest.TestCase):
    """Integration tests for /api/v1/auth/* and API protection."""

    def setUp(self) -> None:
        _reset_auth_globals()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.env_path = self.data_dir / ".env"
        self.env_path.write_text("STOCK_LIST=600519\nGEMINI_API_KEY=test\n", encoding="utf-8")
        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["SECRET_KEY"] = "auth-api-test-secret"
        FakeUserRepository.users = {
            DEFAULT_ADMIN_EMAIL: FakeUser(
                uid=1,
                email=DEFAULT_ADMIN_EMAIL,
                username=DEFAULT_ADMIN_USERNAME,
            ),
        }
        self.user_repo_patch = patch.object(auth_endpoint, "UserRepository", FakeUserRepository)
        self.user_repo_patch.start()
        Config.reset_instance()

    def tearDown(self) -> None:
        self.user_repo_patch.stop()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("SECRET_KEY", None)
        self.temp_dir.cleanup()

    @staticmethod
    def _build_request(cookies=None):
        return SimpleNamespace(
            headers={},
            url=SimpleNamespace(scheme="http"),
            cookies=cookies or {},
            client=SimpleNamespace(host="127.0.0.1"),
        )

    @staticmethod
    def _middleware_request(path: str, cookie_value: str | None = None) -> Request:
        headers = []
        if cookie_value is not None:
            headers.append((b"cookie", f"{auth.COOKIE_NAME}={cookie_value}".encode("utf-8")))
        scope = {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": headers,
            "query_string": b"",
            "scheme": "http",
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "root_path": "",
        }
        return Request(scope)

    def _set_default_admin_password(self, password: str = "mypass456") -> None:
        response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(
                    email=DEFAULT_ADMIN_EMAIL,
                    password=password,
                    passwordConfirm=password,
                ),
            )
        )
        self.assertEqual(response.status_code, 200)

    @staticmethod
    def _jpeg_upload(size=(64, 64)) -> UploadFile:
        stream = io.BytesIO()
        Image.new("RGB", size, color=(32, 120, 200)).save(stream, format="JPEG")
        stream.seek(0)
        return UploadFile(filename="avatar.jpg", file=stream, headers=Headers({"content-type": "image/jpeg"}))

    def _login_default_admin(self, password: str = "mypass456"):
        return asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(email=DEFAULT_ADMIN_EMAIL, password=password),
            )
        )

    def test_auth_status_when_password_not_set(self) -> None:
        data = asyncio.run(auth_endpoint.auth_status(self._build_request()))
        self.assertEqual(set(data.keys()), {"loggedIn", "user"})
        self.assertFalse(data["loggedIn"])
        self.assertIsNone(data["user"])

    def test_auth_status_returns_public_gender_for_logged_in_user(self) -> None:
        user = FakeUserRepository.users[DEFAULT_ADMIN_EMAIL]
        user.password_hash = "mypass456"
        user.extra = {"gender": "female"}

        with patch.object(auth_endpoint, "parse_session_uid", return_value=user.id):
            data = asyncio.run(auth_endpoint.auth_status(self._build_request(cookies={auth.COOKIE_NAME: "test-session"})))

        self.assertTrue(data["loggedIn"])
        self.assertEqual(data["user"]["extra"]["gender"], "female")
        self.assertNotIn("notification", data["user"]["extra"])

    def test_lookup_unknown_email(self) -> None:
        response = asyncio.run(
            auth_endpoint.auth_lookup(
                self._build_request(),
                auth_endpoint.EmailLookupRequest(email="nobody@example.com"),
            )
        )
        self.assertEqual(response.status_code, 401)

    def test_lookup_default_admin_needs_setup(self) -> None:
        data = asyncio.run(
            auth_endpoint.auth_lookup(
                self._build_request(),
                auth_endpoint.EmailLookupRequest(email=DEFAULT_ADMIN_EMAIL),
            )
        )
        self.assertTrue(data["needsPasswordSetup"])

    def test_login_first_time_set_initial_password_requires_relogin(self) -> None:
        response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(
                    email=DEFAULT_ADMIN_EMAIL,
                    password="newpass123",
                    passwordConfirm="newpass123",
                ),
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("set-cookie", response.headers)
        self.assertIn(b'"requiresRelogin":true', response.body)

    def test_login_after_set_normal_login_writes_session_cookie(self) -> None:
        self._set_default_admin_password()

        response = self._login_default_admin()

        self.assertEqual(response.status_code, 200)
        cookie_header = response.headers["set-cookie"]
        self.assertIn(f"{auth.COOKIE_NAME}=", cookie_header)
        session_cookie = cookie_header.split(f"{auth.COOKIE_NAME}=", 1)[1].split(";", 1)[0]
        self.assertTrue(auth.verify_session(session_cookie))

    def test_login_wrong_password_returns_401(self) -> None:
        self._set_default_admin_password("correct6")

        response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(email=DEFAULT_ADMIN_EMAIL, password="wrong"),
            )
        )
        self.assertEqual(response.status_code, 401)

    def test_logout_clears_cookie(self) -> None:
        response = asyncio.run(auth_endpoint.auth_logout())
        self.assertEqual(response.status_code, 204)
        self.assertIn(f"{auth.COOKIE_NAME}=", response.headers["set-cookie"])

    def test_change_password_requires_session(self) -> None:
        self._set_default_admin_password("oldpass6")
        login_response = self._login_default_admin("oldpass6")
        cookie_header = login_response.headers["set-cookie"]
        session_cookie = cookie_header.split(f"{auth.COOKIE_NAME}=", 1)[1].split(";", 1)[0]
        request = self._build_request(cookies={auth.COOKIE_NAME: session_cookie})

        response = asyncio.run(
            auth_endpoint.auth_change_password(
                request,
                auth_endpoint.ChangePasswordRequest(
                    currentPassword="oldpass6",
                    newPassword="newpass6",
                    newPasswordConfirm="newpass6",
                ),
            )
        )
        self.assertEqual(response.status_code, 204)

    def test_profile_get_returns_normalized_extra(self) -> None:
        token = auth.create_session(uid=1)
        request = self._build_request(cookies={auth.COOKIE_NAME: token})

        data = asyncio.run(auth_endpoint.auth_profile(request))

        self.assertEqual(data["email"], DEFAULT_ADMIN_EMAIL)
        self.assertEqual(data["extra"]["gender"], "unknown")
        self.assertEqual(data["extra"]["notification"]["ntfy"], [{"url": ""}])
        self.assertEqual(data["extra"]["notification"]["telegram"], [{"bot_token": "", "chat_id": ""}])

    def test_profile_update_saves_gender_and_notification_extra(self) -> None:
        token = auth.create_session(uid=1)
        request = self._build_request(cookies={auth.COOKIE_NAME: token})

        data = asyncio.run(
            auth_endpoint.auth_update_profile(
                request,
                auth_endpoint.ProfileUpdateRequest(
                    username="Alice",
                    gender="female",
                    notification=auth_endpoint.NotificationProfileConfig(
                        ntfy=[auth_endpoint.NtfyProfileConfig(url="https://ntfy.sh/demo")],
                        telegram=[auth_endpoint.TelegramProfileConfig(bot_token="token", chat_id="42")],
                    ),
                ),
            )
        )

        self.assertEqual(data["username"], "Alice")
        self.assertEqual(data["extra"]["gender"], "female")
        self.assertEqual(data["extra"]["notification"]["ntfy"], [{"url": "https://ntfy.sh/demo"}])
        self.assertEqual(data["extra"]["notification"]["telegram"], [{"bot_token": "token", "chat_id": "42"}])

    def test_avatar_upload_stores_jpeg_and_updates_avatar_url(self) -> None:
        token = auth.create_session(uid=1)
        request = self._build_request(cookies={auth.COOKIE_NAME: token})

        avatar_dir = self.data_dir / "avatars"
        with patch.object(auth_endpoint, "get_avatar_upload_dir", return_value=avatar_dir):
            data = asyncio.run(auth_endpoint.auth_upload_avatar(request, self._jpeg_upload()))

        avatar_path = avatar_dir / "1.jpg"
        self.assertTrue(avatar_path.is_file())
        self.assertTrue(data["user"]["avatarUrl"].startswith("/api/v1/auth/avatar/1.jpg?v="))

    def test_avatar_upload_rejects_non_square_image(self) -> None:
        token = auth.create_session(uid=1)
        request = self._build_request(cookies={auth.COOKIE_NAME: token})

        response = asyncio.run(auth_endpoint.auth_upload_avatar(request, self._jpeg_upload(size=(64, 48))))

        self.assertEqual(response.status_code, 400)

    def test_protected_api_returns_401_without_session(self) -> None:
        request = self._middleware_request("/api/v1/auth/profile")
        middleware = AuthMiddleware(app=MagicMock())

        response = asyncio.run(middleware.dispatch(request, AsyncMock(return_value=Response(status_code=200))))

        self.assertEqual(response.status_code, 401)

    def test_logout_requires_session_in_middleware(self) -> None:
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
        request = self._middleware_request("/api/v1/auth/profile", cookie_value="test-session")
        middleware = AuthMiddleware(app=MagicMock())
        call_next = AsyncMock(return_value=Response(status_code=200))

        with patch("finance_analysis.interfaces.api.middlewares.auth.parse_session_uid", return_value=1):
            with patch("finance_analysis.interfaces.api.middlewares.auth.UserRepository") as repo_cls:
                repo_cls.return_value.get_by_uid.return_value = SimpleNamespace(uid=1)
                response = asyncio.run(middleware.dispatch(request, call_next))

        self.assertEqual(response.status_code, 200)
        call_next.assert_awaited_once()

    def test_protected_api_rejects_session_for_missing_user(self) -> None:
        request = self._middleware_request("/api/v1/auth/profile", cookie_value="test-session")
        middleware = AuthMiddleware(app=MagicMock())
        call_next = AsyncMock(return_value=Response(status_code=200))

        with patch("finance_analysis.interfaces.api.middlewares.auth.parse_session_uid", return_value=999):
            with patch("finance_analysis.interfaces.api.middlewares.auth.UserRepository") as repo_cls:
                repo_cls.return_value.get_by_uid.return_value = None
                response = asyncio.run(middleware.dispatch(request, call_next))

        self.assertEqual(response.status_code, 401)
        call_next.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
