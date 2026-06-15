# -*- coding: utf-8 -*-
"""Database startup bootstrap routines."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.session import DatabaseManager


def bootstrap_database(manager: "DatabaseManager") -> None:
    """Run migrations and initialize required default data."""
    from src.db_migrations import run_alembic_upgrade_head
    from src.repositories.user_repo import UserRepository

    run_alembic_upgrade_head()

    # Mark the manager usable before repository-driven bootstrap work.
    # ``ensure_default_admin`` uses ``get_session()`` on this same manager;
    # delaying this flag leaves a half-initialized singleton that later
    # surfaces as a 500 during first login.
    manager._initialized = True
    try:
        UserRepository(manager).ensure_default_admin()
    except Exception:
        manager._initialized = False
        raise
