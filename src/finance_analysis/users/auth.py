# -*- coding: utf-8 -*-
"""
Web authentication helpers.

Credentials are stored in the database. Session cookies are signed JWTs
(HS256) carrying only uid, signed with SECRET_KEY.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import os
import secrets
import sys
import time
from typing import Optional, Tuple

import jwt
from finance_analysis.config.runtime import get_runtime_config

COOKIE_NAME = "session"
RATE_LIMIT_WINDOW_SEC = 300
RATE_LIMIT_MAX_FAILURES = 5
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_SECONDS = 15 * 24 * 3600
MIN_PASSWORD_LEN = 6

_secret_key: Optional[str] = None
_rate_limit: dict[str, Tuple[int, float]] = {}
_rate_limit_lock = None


def _get_lock():
    """Lazy init threading lock for rate limit state."""
    global _rate_limit_lock
    if _rate_limit_lock is None:
        import threading

        _rate_limit_lock = threading.Lock()
    return _rate_limit_lock


def _ensure_env_loaded() -> None:
    """Ensure .env is loaded before reading config."""
    from finance_analysis.config import load_env

    load_env()


def _load_secret_key() -> str:
    global _secret_key
    if _secret_key is not None:
        return _secret_key

    config = get_runtime_config()
    _sk = config.secret_key

    # 如果 SECRET_KEY 未设置，则随机生成一个满足 HS256 推荐长度的密钥。
    # 配置单例可能残留旧版本生成的短密钥；没有显式环境密钥时也一并修正。
    if not _sk or (not os.getenv("SECRET_KEY") and len(_sk.encode("utf-8")) < 32):
        _sk = secrets.token_urlsafe(32)
    elif len(_sk.encode("utf-8")) < 32:
        _sk = hashlib.sha256(_sk.encode("utf-8")).hexdigest()
    _secret_key = _sk
    return _secret_key


def _jwt_oct_key(secret: str):
    """Build a JWK HMAC key for the Gehirn ``jwt`` package fallback."""
    key = base64.urlsafe_b64encode(secret.encode("utf-8")).rstrip(b"=").decode("ascii")
    return jwt.jwk_from_dict({"kty": "oct", "k": key})


def _jwt_encode(payload: dict, secret: str) -> str:
    """Encode JWT using PyJWT when available, otherwise the installed ``jwt`` API."""
    if hasattr(jwt, "encode"):
        return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)
    return jwt.JWT().encode(payload, _jwt_oct_key(secret), alg=JWT_ALGORITHM)


def _jwt_decode(value: str, secret: str, *, verify_signature: bool = True) -> dict:
    """Decode JWT using PyJWT when available, otherwise the installed ``jwt`` API."""
    if hasattr(jwt, "decode"):
        if verify_signature:
            return jwt.decode(value, secret, algorithms=[JWT_ALGORITHM])
        return jwt.decode(value, options={"verify_signature": False})

    key = _jwt_oct_key(secret) if verify_signature else None
    algorithms = {JWT_ALGORITHM} if verify_signature else None
    return jwt.JWT().decode(
        value,
        key,
        do_verify=verify_signature,
        algorithms=algorithms,
        do_time_check=verify_signature,
    )


def validate_password(pwd: str) -> Optional[str]:
    """Return an error message if invalid, otherwise None."""
    if not pwd or not pwd.strip():
        return "Password is required"
    if len(pwd) < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters"
    return None


def create_session(*, uid: int) -> str:
    """Create a signed JWT session cookie value carrying only uid."""
    if not isinstance(uid, int) or uid <= 0:
        return ""

    now = int(time.time())
    payload = {
        "uid": uid,
        "iat": now,
        "exp": now + JWT_EXPIRE_SECONDS,
    }
    return _jwt_encode(payload, _load_secret_key())


def parse_session_uid(value: str) -> Optional[int]:
    """Verify the JWT session cookie and return the embedded uid."""
    if not value:
        return None
    try:
        payload = _jwt_decode(value, _load_secret_key())
    except Exception:
        return None

    uid = payload.get("uid")
    if not isinstance(uid, int) or uid <= 0:
        return None
    return uid


def verify_session(value: str) -> bool:
    """Return whether the session cookie is a valid, unexpired JWT."""
    return parse_session_uid(value) is not None


def get_client_ip(request) -> str:
    """Get client IP, respecting TRUST_X_FORWARDED_FOR when explicitly enabled."""
    if os.getenv("TRUST_X_FORWARDED_FOR", "false").lower() == "true":
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    if request.client:
        return request.client.host or "127.0.0.1"
    return "127.0.0.1"


def check_rate_limit(ip: str) -> bool:
    """Return True if the IP is under the failed-login limit."""
    lock = _get_lock()
    now = time.time()
    with lock:
        expired_keys = [k for k, (_, ts) in _rate_limit.items() if now - ts > RATE_LIMIT_WINDOW_SEC]
        for k in expired_keys:
            del _rate_limit[k]
        if ip in _rate_limit:
            count, _ = _rate_limit[ip]
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
    """Clear rate limit state after successful login."""
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
    """Register a user by email; password is unset until first web login."""
    _ensure_env_loaded()
    from finance_analysis.database.repositories.user import UserRepository

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
    print(f"User created: uid={user.id} email={user.email} username={user.username} role={user.role}")
    print("Password is unset; user must complete first-time setup on the login page.")
    return 0


def set_password_cli(email: str) -> int:
    """Set or reset a user's password by email."""
    _ensure_env_loaded()
    from finance_analysis.database.repositories.user import UserRepository

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

    repo.set_plain_password(user.id, pwd)
    print(f"Password updated for {email}")
    return 0


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="User account management")
    sub = parser.add_subparsers(dest="command", required=True)

    add_p = sub.add_parser("add_user", help="Add a user with an unset password")
    add_p.add_argument("--email", required=True, help="User email (login identifier)")
    add_p.add_argument("--username", required=True, help="Display username")
    add_p.add_argument("--role", default="user", choices=("user", "admin"), help="User role")

    pwd_p = sub.add_parser("set_password", help="Set or reset a user's password")
    pwd_p.add_argument("--email", required=True, help="User email")

    return parser


def _main() -> int:
    parser = _build_cli_parser()
    if len(sys.argv) <= 1:
        parser.print_help()
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
