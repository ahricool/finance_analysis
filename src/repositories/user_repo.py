# -*- coding: utf-8 -*-
"""User account persistence and password helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.storage import DatabaseManager, User

logger = logging.getLogger(__name__)

PBKDF2_ITERATIONS = 100_000
DEFAULT_ADMIN_USERNAME = "Ahri"
DEFAULT_ADMIN_EMAIL = "whoreahri@gmail.com"
VALID_GENDERS = {"male", "female", "unknown"}


def _normalize_notification_items(items: Any, allowed_keys: List[str]) -> List[Dict[str, str]]:
    if not isinstance(items, list):
        return [{key: "" for key in allowed_keys}]

    normalized: List[Dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized.append({key: str(item.get(key) or "").strip() for key in allowed_keys})

    return normalized or [{key: "" for key in allowed_keys}]


def normalize_user_extra(extra: Any) -> Dict[str, Any]:
    raw = extra if isinstance(extra, dict) else {}
    gender = str(raw.get("gender") or "unknown").strip()
    if gender not in VALID_GENDERS:
        gender = "unknown"

    notification_raw = raw.get("notification") if isinstance(raw.get("notification"), dict) else {}
    return {
        "gender": gender,
        "notification": {
            "ntfy": _normalize_notification_items(notification_raw.get("ntfy"), ["url"]),
            "telegram": _normalize_notification_items(
                notification_raw.get("telegram"),
                ["bot_token", "chat_id"],
            ),
        },
    }


def _hash_password(plain: str) -> str:
    salt = secrets.token_bytes(32)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        plain.encode("utf-8"),
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    salt_b64 = base64.standard_b64encode(salt).decode("ascii")
    hash_b64 = base64.standard_b64encode(derived).decode("ascii")
    return f"{salt_b64}:{hash_b64}"


def _verify_password(plain: str, stored: Optional[str]) -> bool:
    if not stored or ":" not in stored:
        return False
    salt_b64, hash_b64 = stored.split(":", 1)
    try:
        salt = base64.standard_b64decode(salt_b64)
        expected = base64.standard_b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    computed = hashlib.pbkdf2_hmac(
        "sha256",
        plain.encode("utf-8"),
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return hmac.compare_digest(computed, expected)


class UserRepository:
    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager.get_instance()

    def get_by_uid(self, uid: int) -> Optional[User]:
        with self.db.get_session() as session:
            return session.get(User, uid)

    def get_by_username(self, username: str) -> Optional[User]:
        key = (username or "").strip().lower()
        if not key:
            return None
        with self.db.get_session() as session:
            return session.execute(
                select(User).where(func.lower(User.username) == key).limit(1)
            ).scalars().first()

    def get_by_email(self, email: str) -> Optional[User]:
        key = (email or "").strip().lower()
        if not key:
            return None
        with self.db.get_session() as session:
            return session.execute(
                select(User).where(func.lower(User.email) == key).limit(1)
            ).scalars().first()

    def verify_plain_for_uid(self, uid: int, plain: str) -> bool:
        user = self.get_by_uid(uid)
        if user is None or not user.password_hash:
            return False
        return _verify_password(plain, user.password_hash)

    def verify_plain_for_email(self, email: str, plain: str) -> bool:
        user = self.get_by_email(email)
        if user is None or not user.password_hash:
            return False
        return _verify_password(plain, user.password_hash)

    def verify_credentials(self, email: str, password: str) -> Optional[User]:
        user = self.get_by_email(email)
        if user is None or not user.password_hash:
            return None
        if _verify_password(password, user.password_hash):
            return user
        return None

    def set_password_hash(self, uid: int, password_hash: str) -> bool:
        def _write(session: Session) -> bool:
            row = session.get(User, uid)
            if row is None:
                return False
            row.password_hash = password_hash
            session.flush()
            return True

        return self.db._run_write_transaction("users.set_password", _write)

    def set_plain_password(self, uid: int, plain: str) -> None:
        self.set_password_hash(uid, _hash_password(plain))

    def update_profile(
        self,
        uid: int,
        *,
        username: Optional[str] = None,
        gender: Optional[str] = None,
        notification: Optional[Dict[str, Any]] = None,
    ) -> Optional[User]:
        username_val = username.strip() if username is not None else None
        if username is not None and not username_val:
            raise ValueError("username is required")
        if username_val is not None and len(username_val) > 64:
            raise ValueError("username is too long")
        if gender is not None and gender not in VALID_GENDERS:
            raise ValueError("invalid gender")

        def _write(session: Session) -> Optional[int]:
            row = session.get(User, uid)
            if row is None:
                return None
            if username_val is not None:
                row.username = username_val
            next_extra = normalize_user_extra(row.extra)
            if gender is not None:
                next_extra["gender"] = gender
            if notification is not None:
                next_extra["notification"] = normalize_user_extra({"notification": notification})["notification"]
            row.extra = next_extra
            session.flush()
            return row.id

        updated_uid = self.db._run_write_transaction("users.update_profile", _write)
        return self.get_by_uid(updated_uid) if updated_uid else None

    def set_avatar_url(self, uid: int, avatar_url: str) -> Optional[User]:
        def _write(session: Session) -> Optional[int]:
            row = session.get(User, uid)
            if row is None:
                return None
            row.avatar_url = avatar_url
            row.extra = normalize_user_extra(row.extra)
            session.flush()
            return row.id

        updated_uid = self.db._run_write_transaction("users.set_avatar_url", _write)
        return self.get_by_uid(updated_uid) if updated_uid else None

    def any_user_has_password(self) -> bool:
        with self.db.get_session() as session:
            stmt = select(User.id).where(User.password_hash.is_not(None)).limit(1)
            return session.execute(stmt).scalar() is not None

    def count_users(self) -> int:
        with self.db.get_session() as session:
            return int(session.scalar(select(func.count()).select_from(User)) or 0)

    def create_user(
        self,
        *,
        email: str,
        username: str,
        role: str = "user",
        password: Optional[str] = None,
    ) -> User:
        """Create a user. Email must be unique; username may duplicate others."""
        email_key = (email or "").strip().lower()
        username_val = (username or "").strip()
        if not email_key:
            raise ValueError("email is required")
        if not username_val:
            raise ValueError("username is required")
        if self.get_by_email(email_key):
            raise ValueError(f"email already registered: {email_key}")

        pwd_hash = _hash_password(password) if password else None

        def _write(session: Session) -> int:
            row = User(
                email=email_key,
                username=username_val,
                password_hash=pwd_hash,
                avatar_url=None,
                role=role,
                extra={},
            )
            session.add(row)
            session.flush()
            return row.id

        uid = self.db._run_write_transaction("users.create", _write)
        created = self.get_by_uid(uid)
        if created is None:
            raise RuntimeError("failed to load user after create")
        return created

    def user_needs_password_setup(self, email: str) -> Optional[bool]:
        """Return True if user exists and has no password; False if has password; None if unknown."""
        user = self.get_by_email(email)
        if user is None:
            return None
        return not bool(user.password_hash)

    def ensure_default_admin(self) -> int:
        """
        Ensure built-in admin ``Ahri`` exists. Returns the admin uid.

        Password is left unset until the user completes first-time setup on the login page.
        """
        with self.db.get_session() as session:
            existing = session.execute(
                select(User)
                .where(func.lower(User.email) == DEFAULT_ADMIN_EMAIL.lower())
                .limit(1)
            ).scalars().first()
            if existing:
                return existing.id

            row = User(
                username=DEFAULT_ADMIN_USERNAME,
                email=DEFAULT_ADMIN_EMAIL,
                password_hash=None,
                avatar_url=None,
                role="admin",
                extra={},
            )
            session.add(row)
            session.flush()
            uid = row.id
            session.commit()
            logger.info(
                "Created default admin user %s (%s) without password — set via first login",
                DEFAULT_ADMIN_USERNAME,
                DEFAULT_ADMIN_EMAIL,
            )
            return uid

    def to_public_dict(self, user: User) -> Dict[str, Any]:
        return {
            "uid": user.id,
            "username": user.username,
            "email": user.email,
            "avatarUrl": user.avatar_url,
            "role": user.role,
            "extra": {
                "gender": normalize_user_extra(user.extra)["gender"],
            },
        }

    def to_profile_dict(self, user: User) -> Dict[str, Any]:
        payload = self.to_public_dict(user)
        payload["extra"] = normalize_user_extra(user.extra)
        return payload
