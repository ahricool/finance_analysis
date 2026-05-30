# -*- coding: utf-8 -*-
"""User account persistence and password helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.storage import DatabaseManager, User

logger = logging.getLogger(__name__)

PBKDF2_ITERATIONS = 100_000
DEFAULT_ADMIN_USERNAME = "ahri"
DEFAULT_ADMIN_EMAIL = "ahri@localhost"


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

    def get_by_uid(self, uid: str) -> Optional[User]:
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

    def verify_plain_for_uid(self, uid: str, plain: str) -> bool:
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

    def set_password_hash(self, uid: str, password_hash: str) -> bool:
        def _write(session: Session) -> bool:
            row = session.get(User, uid)
            if row is None:
                return False
            row.password_hash = password_hash
            session.flush()
            return True

        return self.db._run_write_transaction("users.set_password", _write)

    def set_plain_password(self, uid: str, plain: str) -> None:
        self.set_password_hash(uid, _hash_password(plain))

    def any_user_has_password(self) -> bool:
        with self.db.get_session() as session:
            stmt = select(User.uid).where(User.password_hash.is_not(None)).limit(1)
            return session.execute(stmt).scalar() is not None

    def count_users(self) -> int:
        with self.db.get_session() as session:
            return int(session.scalar(select(func.count()).select_from(User)) or 0)

    def ensure_default_admin(self) -> str:
        """
        Ensure built-in admin ``ahri`` exists. Returns the admin uid.

        Password:
        - If ``AHRI_INITIAL_PASSWORD`` is set, assign that password on first create
          or when the user exists but has no password yet.
        - Otherwise leave password unset until first-time setup via login or settings.
        """
        initial = (os.environ.get("AHRI_INITIAL_PASSWORD") or "").strip()
        with self.db.get_session() as session:
            existing = session.execute(
                select(User)
                .where(func.lower(User.email) == DEFAULT_ADMIN_EMAIL)
                .limit(1)
            ).scalars().first()
            if existing:
                if initial and not existing.password_hash:
                    existing.password_hash = _hash_password(initial)
                    session.commit()
                    logger.info("Default admin %s password set from AHRI_INITIAL_PASSWORD", DEFAULT_ADMIN_USERNAME)
                return existing.uid

            uid = str(uuid.uuid4())
            pwd_hash = _hash_password(initial) if initial else None
            row = User(
                uid=uid,
                username=DEFAULT_ADMIN_USERNAME,
                email=DEFAULT_ADMIN_EMAIL,
                password_hash=pwd_hash,
                avatar_url=None,
                role="admin",
                extra={},
            )
            session.add(row)
            session.commit()
            if initial:
                logger.info("Created default admin user %s (password from AHRI_INITIAL_PASSWORD)", DEFAULT_ADMIN_USERNAME)
            else:
                logger.info(
                    "Created default admin user %s without password — set via first login or AHRI_INITIAL_PASSWORD",
                    DEFAULT_ADMIN_USERNAME,
                )
            return uid

    def to_public_dict(self, user: User) -> Dict[str, Any]:
        return {
            "uid": user.uid,
            "username": user.username,
            "email": user.email,
            "avatarUrl": user.avatar_url,
            "role": user.role,
        }
