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


@dataclass
class PostgreSQLAdvisoryLock:
    """A session-level, non-blocking advisory lock held by one connection."""

    lock_id: TaskAdvisoryLockId
    db_manager: DatabaseManager | None = None
    connection: Any = None
    acquired: bool = False

    def acquire(self) -> bool:
        if self.connection is not None:
            raise RuntimeError("Advisory lock instance cannot be acquired twice")
        db = self.db_manager or DatabaseManager.get_instance()
        self.connection = db.connect()
        try:
            self.acquired = bool(
                self.connection.execute(
                    text("SELECT pg_try_advisory_lock(:namespace, :lock_id)"),
                    {"namespace": TASK_MUTEX_NAMESPACE, "lock_id": int(self.lock_id)},
                ).scalar_one()
            )
            if not self.acquired:
                self.connection.close()
                self.connection = None
            return self.acquired
        except Exception:
            self.connection.close()
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
                if not unlocked:
                    logger.warning("PostgreSQL advisory lock was not held at release: lock_id=%s", self.lock_id.name)
        finally:
            self.acquired = False
            connection.close()

    def __enter__(self) -> "PostgreSQLAdvisoryLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        del exc_type, exc, traceback
        self.release()
