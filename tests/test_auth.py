# -*- coding: utf-8 -*-
"""Unit tests for src.auth module."""

import os
import time
import unittest
from unittest.mock import patch

import src.auth as auth


def _reset_auth_globals() -> None:
    """Reset auth module globals for test isolation."""
    auth._secret_key = None
    auth._rate_limit = {}


class AuthValidationTestCase(unittest.TestCase):
    """Test password validation."""

    def setUp(self) -> None:
        _reset_auth_globals()

    def test_validate_password_empty(self) -> None:
        self.assertIsNotNone(auth.validate_password(""))
        self.assertIsNotNone(auth.validate_password("   "))

    def test_validate_password_too_short(self) -> None:
        self.assertIsNotNone(auth.validate_password("12345"))

    def test_validate_password_valid(self) -> None:
        self.assertIsNone(auth.validate_password("123456"))
        self.assertIsNone(auth.validate_password("password123"))


class AuthSessionTestCase(unittest.TestCase):
    """Test session creation and verification."""

    def setUp(self) -> None:
        _reset_auth_globals()

    def _patch_env_and_run(self, test_fn=None):
        with patch.dict(os.environ, {"SECRET_KEY": "unit-test-secret"}):
            _reset_auth_globals()
            if test_fn:
                return test_fn()

    def test_create_session_returns_jwt(self) -> None:
        def run():
            tok = auth.create_session(user_uid=1)
            self.assertTrue(tok, "session token should be non-empty")
            self.assertEqual(len(tok.split(".")), 3, "JWT format: header.payload.signature")
            self.assertEqual(auth.parse_session_user_uid(tok), 1)

        self._patch_env_and_run(test_fn=run)

    def test_session_jwt_carries_only_uid_and_expiry(self) -> None:
        def run():
            tok = auth.create_session(user_uid=2)
            payload = auth._jwt_decode(tok, auth._load_secret_key(), verify_signature=False)
            self.assertEqual(payload["uid"], 2)
            self.assertEqual(set(payload.keys()), {"uid", "iat", "exp"})
            self.assertEqual(payload["exp"] - payload["iat"], auth.JWT_EXPIRE_SECONDS)

        self._patch_env_and_run(test_fn=run)

    def test_verify_session_valid_token(self) -> None:
        def run():
            tok = auth.create_session(user_uid=3)
            self.assertTrue(auth.verify_session(tok))

        self._patch_env_and_run(test_fn=run)

    def test_verify_session_expired(self) -> None:
        def run():
            past = time.time() - (auth.JWT_EXPIRE_SECONDS + 3600)
            with patch.object(auth, "time") as mock_time:
                mock_time.time.return_value = past
                tok = auth.create_session(user_uid=4)
            self.assertFalse(auth.verify_session(tok), "expired token should be rejected")

        self._patch_env_and_run(test_fn=run)

    def test_verify_session_invalid_format(self) -> None:
        def run():
            self.assertFalse(auth.verify_session(""))
            self.assertFalse(auth.verify_session("a.b"))
            self.assertFalse(auth.verify_session("invalid"))

        self._patch_env_and_run(test_fn=run)

    def test_load_secret_key_generates_when_env_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SECRET_KEY", None)
            _reset_auth_globals()
            self.assertTrue(auth._load_secret_key())


class AuthRateLimitTestCase(unittest.TestCase):
    """Test rate limiting."""

    def setUp(self) -> None:
        _reset_auth_globals()

    def test_rate_limit_allows_under_limit(self) -> None:
        self.assertTrue(auth.check_rate_limit("192.168.1.1"))

    def test_rate_limit_blocks_after_max_failures(self) -> None:
        ip = "10.0.0.99"
        for _ in range(auth.RATE_LIMIT_MAX_FAILURES):
            auth.record_login_failure(ip)
        self.assertFalse(auth.check_rate_limit(ip))

    def test_clear_rate_limit_resets_ip(self) -> None:
        ip = "10.0.0.100"
        for _ in range(auth.RATE_LIMIT_MAX_FAILURES):
            auth.record_login_failure(ip)
        self.assertFalse(auth.check_rate_limit(ip))
        auth.clear_rate_limit(ip)
        self.assertTrue(auth.check_rate_limit(ip))


if __name__ == "__main__":
    unittest.main()
