# -*- coding: utf-8 -*-
"""
Web authentication module.

Credentials are stored only in the database (users.password_hash).
Session cookies are JWTs (HS256) carrying only the user uid. The signing
secret is sourced from the SESSION_SECRET environment variable.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import logging
import os
import secrets
import sys
import time
from typing import Optional, Tuple

import jwt

logger = logging.getLogger(__name__)

COOKIE_NAME = "session"
PBKDF2_ITERATIONS = 100_000
RATE_LIMIT_WINDOW_SEC = 300
RATE_LIMIT_MAX_FAILURES = 5
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 180
JWT_EXPIRE_SECONDS = JWT_EXPIRE_DAYS * 24 * 3600
MIN_PASSWORD_LEN = 6

_session_secret: Optional[bytes] = None
_rate_limit: dict[str, Tuple[int, float]] = {}
_rate_limit_lock = None


def _get_lock():
    """Lazy init threading lock for rate limit dict."""
    global _rate_limit_lock
    if _rate_limit_lock is None:
        import threading

        _rate_limit_lock = threading.Lock()
    return _rate_limit_lock


def _ensure_env_loaded() -> None:
    """Ensure .env is loaded before reading config."""
    from src.config import setup_env

    setup_env()



def _load_session_secret() -> Optional[bytes]:
    global _session_secret
    if _session_secret is not None:
        return _session_secret

    raw = os.getenv("SECRET_KEY")
    if raw:
        _session_secret = hashlib.sha256(raw.encode("utf-8")).digest()
        return _session_secret
    else:
        raise ValueError("SECRET_KEY is not set")



def is_auth_enabled() -> bool:
    """Authentication is always enabled."""
    return True


def is_password_changeable() -> bool:
    """Return whether password can be changed via web/CLI."""
    return True


def _get_session_secret() -> Optional[bytes]:
    """Return session signing secret."""
    return _load_session_secret()


def validate_password(pwd: str) -> Optional[str]:
    """Return error message if invalid, None if valid."""
    if not pwd or not pwd.strip():
        return "密码不能为空"
    if len(pwd) < MIN_PASSWORD_LEN:
        return f"密码至少 {MIN_PASSWORD_LEN} 位"
    return None


def create_session(*, user_uid: str) -> str:
    """Create a signed JWT session cookie value carrying only the user uid.

    The token expires after JWT_EXPIRE_DAYS (180 days) and is signed (HS256)
    with the secret loaded from the SESSION_SECRET environment variable.
    """
    secret = _get_session_secret()
    if not secret or not (user_uid or "").strip():
        return ""
    now = int(time.time())
    payload = {
        "uid": user_uid,
        "iat": now,
        "exp": now + JWT_EXPIRE_SECONDS,
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def parse_session_user_uid(value: str) -> Optional[str]:
    """Verify the JWT session cookie and return the embedded user uid, or None."""
    secret = _get_session_secret()
    if not secret or not value:
        return None
    try:
        payload = jwt.decode(value, secret, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return None
    uid = payload.get("uid")
    if not isinstance(uid, str) or not uid:
        return None
    return uid


def verify_session(value: str) -> bool:
    """Verify session cookie and check expiry."""
    return parse_session_user_uid(value) is not None


def get_client_ip(request) -> str:
    """Get client IP, respecting TRUST_X_FORWARDED_FOR."""
    if os.getenv("TRUST_X_FORWARDED_FOR", "false").lower() == "true":
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    if request.client:
        return request.client.host or "127.0.0.1"
    return "127.0.0.1"


def check_rate_limit(ip: str) -> bool:
    """Return True if under limit, False if rate limited."""
    lock = _get_lock()
    now = time.time()
    with lock:
        expired_keys = [k for k, (_, ts) in _rate_limit.items() if now - ts > RATE_LIMIT_WINDOW_SEC]
        for k in expired_keys:
            del _rate_limit[k]
        if ip in _rate_limit:
            count, first_ts = _rate_limit[ip]
            if count >= RATE_LIMIT_MAX_FAILURES:
                return False
        return True


def record_login_failure(ip: str) -> None:
    """Record a failed login attempt for rate limiting."""
    lock = _get_lock()
    now = time.time()
    with lock:
        if ip in _rate_limit:
            count, first_ts = _rate_limit[ip]
            if now - first_ts > RATE_LIMIT_WINDOW_SEC:
                _rate_limit[ip] = (1, now)
            else:
                _rate_limit[ip] = (count + 1, first_ts)
        else:
            _rate_limit[ip] = (1, now)


def clear_rate_limit(ip: str) -> None:
    """Clear rate limit for IP after successful login."""
    lock = _get_lock()
    with lock:
        _rate_limit.pop(ip, None)


def _prompt_password_twice() -> Optional[str]:
    print("Enter password (will not echo):", end=" ")
    pwd = getpass.getpass("")
    err = validate_password(pwd)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return None
    print("Confirm password:", end=" ")
    pwd2 = getpass.getpass("")
    if pwd != pwd2:
        print("Error: Passwords do not match", file=sys.stderr)
        return None
    return pwd


def add_user_cli(email: str, username: str, role: str = "user") -> int:
    """CLI: register a user by email (password unset until first web login)."""
    _ensure_env_loaded()
    from src.repositories.user_repo import UserRepository

    email = (email or "").strip()
    username = (username or "").strip()
    if not email:
        print("Error: email is required", file=sys.stderr)
        return 1
    if not username:
        print("Error: username is required", file=sys.stderr)
        return 1

    repo = UserRepository()
    if repo.get_by_email(email):
        print(f"Error: user with email {email} already exists", file=sys.stderr)
        return 1

    user = repo.create_user(email=email, username=username, role=role)
    print(f"User created: uid={user.uid} email={user.email} username={user.username} role={user.role}")
    print("Password is unset — user must complete first-time setup on the login page.")
    return 0


def set_password_cli(email: str) -> int:
    """CLI: set or reset password for any user by email."""
    _ensure_env_loaded()
    from src.repositories.user_repo import UserRepository

    email = (email or "").strip()
    if not email:
        print("Error: --email is required", file=sys.stderr)
        return 1

    repo = UserRepository()
    user = repo.get_by_email(email)
    if user is None:
        print(f"Error: no user with email {email}", file=sys.stderr)
        return 1

    pwd = _prompt_password_twice()
    if pwd is None:
        return 1

    repo.set_plain_password(user.uid, pwd)
    print(f"Password updated for {email}")
    return 0


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="User account management (database only)")
    sub = parser.add_subparsers(dest="command", required=True)

    add_p = sub.add_parser("add_user", help="Add a user (email must be unique; password unset)")
    add_p.add_argument("--email", required=True, help="User email (login identifier)")
    add_p.add_argument("--username", required=True, help="Display username (may duplicate others)")
    add_p.add_argument("--role", default="user", choices=("user", "admin"), help="User role")

    pwd_p = sub.add_parser("set_password", help="Set or reset a user's password")
    pwd_p.add_argument("--email", required=True, help="User email")

    sub.add_parser(
        "reset_password",
        help="Deprecated alias for set_password (interactive email prompt)",
    )
    return parser


def _main() -> int:
    parser = _build_cli_parser()
    if len(sys.argv) <= 1:
        parser.print_help()
        return 1

    if sys.argv[1] == "reset_password":
        print(
            "Note: reset_password now requires an email. Prefer:\n"
            "  python -m src.auth set_password --email user@example.com",
            file=sys.stderr,
        )
        if len(sys.argv) == 2:
            email = input("Email: ").strip()
            return set_password_cli(email)
        return 1

    args = parser.parse_args()
    if args.command == "add_user":
        return add_user_cli(args.email, args.username, args.role)
    if args.command == "set_password":
        return set_password_cli(args.email)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(_main())
