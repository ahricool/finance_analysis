# -*- coding: utf-8 -*-
"""Resolve the owning user id for persisted analysis artifacts."""

from __future__ import annotations

from typing import Optional


def resolve_owner_uid(uid: Optional[int] = None) -> int:
    """Return an explicit uid or fall back to the default admin account."""
    if uid is not None:
        return int(uid)
    from src.repositories.user_repo import UserRepository

    return UserRepository().ensure_default_admin()
