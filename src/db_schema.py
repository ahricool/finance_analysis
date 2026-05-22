# -*- coding: utf-8 -*-
"""
Lightweight schema migrations for user-scoped columns.

The app uses SQLAlchemy create_all() without Alembic; existing deployments need
explicit ALTER / table rebuild steps when new columns or constraints are added.
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


def _run_sqlite_watch_stock_migration(engine: Engine, table: str, default_uid: str) -> None:
    """Rebuild watch_list or stock_list to replace global unique(code) with (user_id, code)."""
    is_watch = table == "watch_list"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
            CREATE TABLE IF NOT EXISTS {table}__new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id VARCHAR(36) NOT NULL,
                code VARCHAR(16) NOT NULL,
                name VARCHAR(64),
                notes TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
                {", quantity INTEGER NOT NULL DEFAULT 0" if not is_watch else ""}
            )
            """
            )
        )
        if is_watch:
            conn.execute(
                text(
                    f"""
                INSERT INTO {table}__new (user_id, code, name, notes, created_at, updated_at)
                SELECT :uid, code, name, notes, created_at, updated_at FROM {table}
                """
                ),
                {"uid": default_uid},
            )
        else:
            conn.execute(
                text(
                    f"""
                INSERT INTO {table}__new (user_id, code, name, quantity, notes, created_at, updated_at)
                SELECT :uid, code, name, quantity, notes, created_at, updated_at FROM {table}
                """
                ),
                {"uid": default_uid},
            )
        conn.execute(text(f"DROP TABLE {table}"))
        conn.execute(text(f"ALTER TABLE {table}__new RENAME TO {table}"))
        conn.execute(
            text(f"CREATE UNIQUE INDEX IF NOT EXISTS uix_{table}_user_code ON {table} (user_id, code)")
        )
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_user ON {table} (user_id)"))


def _add_column_sqlite(engine: Engine, table: str, ddl: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(ddl))


def _add_column_postgresql(engine: Engine, table: str, ddl: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(ddl))


def run_user_scoped_migrations(engine: Engine, default_user_uid: str) -> None:
    """
    Ensure user_id (or equivalent) exists on domain tables and backfill.

    Args:
        engine: SQLAlchemy engine
        default_user_uid: uid assigned to legacy rows (default admin)
    """
    is_sqlite = engine.url.get_backend_name() == "sqlite"
    is_pg = engine.url.get_backend_name() == "postgresql"

    if not _table_exists(engine, "users"):
        logger.warning("users table missing; skip user-scoped migrations")
        return

    # --- watch_list ---
    if _table_exists(engine, "watch_list"):
        cols = _column_names(engine, "watch_list")
        if "user_id" not in cols:
            if is_sqlite:
                _run_sqlite_watch_stock_migration(engine, "watch_list", default_user_uid)
            elif is_pg:
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)"
                        )
                    )
                    conn.execute(
                        text(
                            "UPDATE watch_list SET user_id = :uid WHERE user_id IS NULL"
                        ),
                        {"uid": default_user_uid},
                    )
                    conn.execute(
                        text(
                            "ALTER TABLE watch_list ALTER COLUMN user_id SET NOT NULL"
                        )
                    )
                logger.info("watch_list.user_id added (PostgreSQL); unique(code) may still exist — manual cleanup if needed")
            else:
                logger.warning("Unsupported DB backend for watch_list migration")

    # --- stock_list ---
    if _table_exists(engine, "stock_list"):
        cols = _column_names(engine, "stock_list")
        if "user_id" not in cols:
            if is_sqlite:
                _run_sqlite_watch_stock_migration(engine, "stock_list", default_user_uid)
            elif is_pg:
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "ALTER TABLE stock_list ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)"
                        )
                    )
                    conn.execute(
                        text(
                            "UPDATE stock_list SET user_id = :uid WHERE user_id IS NULL"
                        ),
                        {"uid": default_user_uid},
                    )
                    conn.execute(
                        text(
                            "ALTER TABLE stock_list ALTER COLUMN user_id SET NOT NULL"
                        )
                    )
                logger.info("stock_list.user_id added (PostgreSQL)")

    # --- calendar_signals ---
    if _table_exists(engine, "calendar_signals"):
        if "user_id" not in _column_names(engine, "calendar_signals"):
            ddl_sqlite = (
                "ALTER TABLE calendar_signals ADD COLUMN user_id VARCHAR(36) NOT NULL DEFAULT '"
                + default_user_uid.replace("'", "''")
                + "'"
            )
            if is_sqlite:
                _add_column_sqlite(engine, "calendar_signals", ddl_sqlite)
            elif is_pg:
                _add_column_postgresql(
                    engine,
                    "calendar_signals",
                    "ALTER TABLE calendar_signals ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)",
                )
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "UPDATE calendar_signals SET user_id = :uid WHERE user_id IS NULL"
                        ),
                        {"uid": default_user_uid},
                    )
                    conn.execute(
                        text(
                            "ALTER TABLE calendar_signals ALTER COLUMN user_id SET NOT NULL"
                        )
                    )

    # --- conversation_messages (nullable: bot / legacy rows may omit user) ---
    if _table_exists(engine, "conversation_messages"):
        if "user_id" not in _column_names(engine, "conversation_messages"):
            if is_sqlite:
                _add_column_sqlite(
                    engine,
                    "conversation_messages",
                    "ALTER TABLE conversation_messages ADD COLUMN user_id VARCHAR(36)",
                )
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "UPDATE conversation_messages SET user_id = :uid WHERE user_id IS NULL"
                        ),
                        {"uid": default_user_uid},
                    )
            elif is_pg:
                _add_column_postgresql(
                    engine,
                    "conversation_messages",
                    "ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)",
                )
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "UPDATE conversation_messages SET user_id = :uid WHERE user_id IS NULL"
                        ),
                        {"uid": default_user_uid},
                    )

    # --- llm_usage ---
    if _table_exists(engine, "llm_usage"):
        if "user_id" not in _column_names(engine, "llm_usage"):
            if is_sqlite:
                _add_column_sqlite(
                    engine,
                    "llm_usage",
                    "ALTER TABLE llm_usage ADD COLUMN user_id VARCHAR(36)",
                )
                with engine.begin() as conn:
                    conn.execute(
                        text("UPDATE llm_usage SET user_id = :uid WHERE user_id IS NULL"),
                        {"uid": default_user_uid},
                    )
            elif is_pg:
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
