"""PostgreSQL advisory locks for the small set of mutex-protected Celery jobs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from sqlalchemy import text

from finance_analysis.database.session import DatabaseManager

logger = logging.getLogger(__name__)

# Fixed two-key namespace. The first key groups finance-analysis task mutexes;
# the second key is a readable, stable enum value. Never derive these with
# Python hash(), whose output changes between interpreter processes.
TASK_MUTEX_NAMESPACE = 20_260_831


class TaskAdvisoryLockId(IntEnum):
    CN_DAILY_MARKET_DATA_SYNC = 1
    US_DAILY_MARKET_DATA_SYNC = 2
    CN_INTRADAY_ANALYSIS = 3
    US_INTRADAY_ANALYSIS = 4
    STOCK_ANALYSIS = 5


@dataclass
class PostgreSQLAdvisoryLock:
    """A session-level advisory lock held by one connection without an open transaction."""

    lock_id: TaskAdvisoryLockId
    db_manager: DatabaseManager | None = None
    blocking: bool = False
    connection: Any = None
    acquired: bool = False

    def acquire(self) -> bool:
        if self.connection is not None:
            raise RuntimeError("Advisory lock instance cannot be acquired twice")
        db = self.db_manager or DatabaseManager.get_instance()
        self.connection = db.connect()
        try:
            function_name = "pg_advisory_lock" if self.blocking else "pg_try_advisory_lock"
            result = self.connection.execute(
                text(f"SELECT {function_name}(:namespace, :lock_id)"),
                {"namespace": TASK_MUTEX_NAMESPACE, "lock_id": int(self.lock_id)},
            )
            value = result.scalar_one()
            self.acquired = True if self.blocking else bool(value)
            # SQLAlchemy autobegins for SELECT. Commit immediately so the
            # session lock remains held without leaving the worker idle in a
            # transaction during the business task.
            self.connection.commit()
            if not self.acquired:
                self.connection.close()
                self.connection = None
            return self.acquired
        except Exception:
            self._invalidate_and_close(self.connection)
            self.connection = None
            raise

    def release(self) -> None:
        connection = self.connection
        self.connection = None
        if connection is None:
            return
        try:
            if self.acquired:
                unlocked = bool(
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:namespace, :lock_id)"),
                        {"namespace": TASK_MUTEX_NAMESPACE, "lock_id": int(self.lock_id)},
                    ).scalar_one()
                )
                connection.commit()
                if not unlocked:
                    logger.warning("PostgreSQL advisory lock was not held at release: lock_id=%s", self.lock_id.name)
        except Exception:
            self._invalidate_and_close(connection)
            raise
        finally:
            self.acquired = False
            if not connection.closed:
                connection.close()

    @staticmethod
    def _invalidate_and_close(connection: Any) -> None:
        try:
            connection.invalidate()
        except Exception:
            logger.exception("Failed to invalidate advisory-lock connection")
        try:
            connection.close()
        except Exception:
            logger.exception("Failed to close invalidated advisory-lock connection")

    def __enter__(self) -> "PostgreSQLAdvisoryLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        del exc_type, exc, traceback
        self.release()
