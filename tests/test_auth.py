# -*- coding: utf-8 -*-
"""Unit tests for src.auth module."""

import hashlib
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import src.auth as auth


def _reset_auth_globals() -> None:
    """Reset auth module globals for test isolation."""
    auth._session_secret = None
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
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.addCleanup(self.temp_dir.cleanup)

    def _patch_env_and_run(
        self, auth_enabled: bool = True, test_fn=None
    ):
        with patch.object(auth, "_get_data_dir", return_value=self.data_dir):
            if test_fn:
                return test_fn()

    def test_create_session_returns_signed_payload(self) -> None:
        def run():
            tok = auth.create_session(user_uid="u-test-1")
            self.assertTrue(tok, "session token should be non-empty")
            parts = tok.rsplit(".", 1)
            self.assertEqual(len(parts), 2, "format: v2.nonce.ts.uid.signature")
            body, sig = parts
            segs = body.split(".")
            self.assertEqual(len(segs), 4, "v2 + nonce + ts + uid")
            self.assertEqual(segs[0], "v2")
            self.assertTrue(segs[1])
            self.assertTrue(segs[2].isdigit())
            self.assertEqual(segs[3], "u-test-1")
            self.assertTrue(sig)
            return tok

        self._patch_env_and_run(test_fn=run)

    def test_verify_session_valid_token(self) -> None:
        def run():
            tok = auth.create_session(user_uid="u-test-2")
            self.assertTrue(auth.verify_session(tok))

        self._patch_env_and_run(test_fn=run)

    def test_verify_session_expired(self) -> None:
        def run():
            past = time.time() - 48 * 3600
            with patch.object(auth, "time") as mock_time:
                mock_time.time.return_value = past
                tok = auth.create_session(user_uid="u-exp")
            self.assertFalse(auth.verify_session(tok), "48h-old token should be expired")

        self._patch_env_and_run(test_fn=run)

    def test_verify_session_invalid_format(self) -> None:
        def run():
            self.assertFalse(auth.verify_session(""))
            self.assertFalse(auth.verify_session("a.b"))
            self.assertFalse(auth.verify_session("invalid"))

        self._patch_env_and_run(test_fn=run)

    def test_rotate_session_secret_overwrites_existing(self) -> None:
        def run():
            secret_path = self.data_dir / ".session_secret"
            secret_path.write_bytes(b"a" * 32)
            secret_path.chmod(0o600)
            old_secret = secret_path.read_bytes()

            auth.rotate_session_secret()

            new_secret = secret_path.read_bytes()
            self.assertNotEqual(old_secret, new_secret)
            self.assertEqual(auth._session_secret, new_secret)

        self._patch_env_and_run(test_fn=run)

    def test_load_session_secret_regenerates_invalid_length(self) -> None:
        def run():
            secret_path = self.data_dir / ".session_secret"
            secret_path.write_bytes(b"x")
            secret_path.chmod(0o600)

            tok = auth.create_session(user_uid="u-load")
            self.assertTrue(tok)

            new_secret = secret_path.read_bytes()
            self.assertEqual(len(new_secret), 32)
            self.assertNotEqual(new_secret, b"x")

        self._patch_env_and_run(test_fn=run)

    def test_refresh_auth_state_clears_session_secret_cache(self) -> None:
        def run():
            first_secret = auth.create_session(user_uid="u-refresh")
            self.assertTrue(first_secret)
            self.assertIsNotNone(auth._session_secret)

            auth._session_secret = b"x" * 32
            auth.refresh_auth_state()
            self.assertNotEqual(auth._session_secret, b"x" * 32)

        self._patch_env_and_run(test_fn=run)


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


class AuthEnabledTestCase(unittest.TestCase):
    def test_is_auth_enabled_always_true(self) -> None:
        self.assertTrue(auth.is_auth_enabled())


if __name__ == "__main__":
    unittest.main()
