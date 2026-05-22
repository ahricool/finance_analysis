# -*- coding: utf-8 -*-
"""
Lightweight schema migrations for user-scoped columns (PostgreSQL).

The canonical schema is managed by **Alembic** (see ``alembic/`` and
``docs/MIGRATIONS.md``). This module retains small, idempotent SQL fixes for
legacy rows (e.g. backfilling ``user_id``) that are not worth encoding as
versioned migrations.
"""

from __future__ import annotations

import logging
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _table_exists(engine: Engine, name: str) -> bool:
    return inspect(engine).has_table(name)


def _column_names(engine: Engine, table: str) -> set[str]:
    if not _table_exists(engine, table):
        return set()
    return {c["name"] for c in inspect(engine).get_columns(table)}


def _add_column_postgresql(engine: Engine, table: str, ddl: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(ddl))


def run_user_scoped_migrations(engine: Engine, default_user_uid: str) -> None:
    """
    Ensure user_id (or equivalent) exists on domain tables and backfill.

    Args:
        engine: SQLAlchemy engine (PostgreSQL only)
        default_user_uid: uid assigned to legacy rows (default admin)
    """
    if engine.url.get_backend_name() != "postgresql":
        logger.warning(
            "run_user_scoped_migrations skipped: backend=%s (PostgreSQL required)",
            engine.url.get_backend_name(),
        )
        return

    if not _table_exists(engine, "users"):
        logger.warning("users table missing; skip user-scoped migrations")
        return

    # --- watch_list ---
    if _table_exists(engine, "watch_list"):
        cols = _column_names(engine, "watch_list")
        if "user_id" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)")
                )
                conn.execute(
                    text("UPDATE watch_list SET user_id = :uid WHERE user_id IS NULL"),
                    {"uid": default_user_uid},
                )
                conn.execute(text("ALTER TABLE watch_list ALTER COLUMN user_id SET NOT NULL"))
            logger.info(
                "watch_list.user_id added (PostgreSQL); unique(code) may still exist — manual cleanup if needed"
            )

    # --- stock_list ---
    if _table_exists(engine, "stock_list"):
        cols = _column_names(engine, "stock_list")
        if "user_id" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE stock_list ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)")
                )
                conn.execute(
                    text("UPDATE stock_list SET user_id = :uid WHERE user_id IS NULL"),
                    {"uid": default_user_uid},
                )
                conn.execute(text("ALTER TABLE stock_list ALTER COLUMN user_id SET NOT NULL"))
            logger.info("stock_list.user_id added (PostgreSQL)")

    # --- calendar_signals ---
    if _table_exists(engine, "calendar_signals"):
        if "user_id" not in _column_names(engine, "calendar_signals"):
            _add_column_postgresql(
                engine,
                "calendar_signals",
                "ALTER TABLE calendar_signals ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)",
            )
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE calendar_signals SET user_id = :uid WHERE user_id IS NULL"),
                    {"uid": default_user_uid},
                )
                conn.execute(text("ALTER TABLE calendar_signals ALTER COLUMN user_id SET NOT NULL"))

    # --- conversation_messages (nullable: bot / legacy rows may omit user) ---
    if _table_exists(engine, "conversation_messages"):
        if "user_id" not in _column_names(engine, "conversation_messages"):
            _add_column_postgresql(
                engine,
                "conversation_messages",
                "ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)",
            )
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE conversation_messages SET user_id = :uid WHERE user_id IS NULL"),
                    {"uid": default_user_uid},
                )

    # --- llm_usage ---
    if _table_exists(engine, "llm_usage"):
        if "user_id" not in _column_names(engine, "llm_usage"):
            _add_column_postgresql(
                engine,
                "llm_usage",
                "ALTER TABLE llm_usage ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)",
            )
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE llm_usage SET user_id = :uid WHERE user_id IS NULL"),
                    {"uid": default_user_uid},
                )

    # --- portfolio_accounts.owner_id backfill ---
    if _table_exists(engine, "portfolio_accounts"):
        cols = _column_names(engine, "portfolio_accounts")
        if "owner_id" in cols:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE portfolio_accounts SET owner_id = :uid "
                        "WHERE owner_id IS NULL OR owner_id = ''"
                    ),
                    {"uid": default_user_uid},
                )
