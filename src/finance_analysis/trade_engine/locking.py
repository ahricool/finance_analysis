"""Per-user, per-market session mutex without an open business transaction."""

from ..tasks.advisory_lock import PostgreSQLAdvisoryLock

# Distinct from scheduled-job namespaces; uid is a PostgreSQL Integer.
MARKET_LOCK_NAMESPACES = {"CN": 20_260_921, "US": 20_260_922}


def market_decision_lock(db, uid: int, market: str) -> PostgreSQLAdvisoryLock:
    return PostgreSQLAdvisoryLock(
        lock_id=uid, namespace=MARKET_LOCK_NAMESPACES[market], db_manager=db,
    )
