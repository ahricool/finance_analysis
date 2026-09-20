"""Crypto SQL and atomic state/snapshot transitions."""

from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from finance_analysis.core.time import coerce_aware_utc
from finance_analysis.crypto.models import StrategyState
from finance_analysis.database.models.crypto import CryptoStrategySnapshot, CryptoStrategyState


def values(row):
    result = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    return {key: coerce_aware_utc(value) if isinstance(value, datetime) else value for key, value in result.items()}


class CryptoRepository:
    def __init__(self, db_manager=None):
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager

            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    def signals(self, limit=50, *, start=None, end=None, actions_only=False):
        query = select(CryptoStrategySnapshot).where(CryptoStrategySnapshot.symbol == "BTCUSDT")
        if start is not None:
            query = query.where(CryptoStrategySnapshot.evaluated_at >= start)
        if end is not None:
            query = query.where(CryptoStrategySnapshot.evaluated_at <= end)
        if actions_only:
            query = query.where(CryptoStrategySnapshot.action.in_(("BUY", "EXIT")))
        query = query.order_by(CryptoStrategySnapshot.evaluated_at.desc())
        if limit is not None:
            query = query.limit(limit)
        with self.db.get_session() as session:
            return [values(row) for row in session.scalars(query)]

    def state(self):
        with self.db.get_session() as session:
            row = session.get(CryptoStrategyState, "BTCUSDT")
            return StrategyState(**values(row)) if row else StrategyState()

    def evaluate_once(self, at: datetime, calculate):
        """Serialize evaluations, refuse replays, commit state and immutable snapshot together."""
        with self.db.session_scope() as session:
            session.execute(
                insert(CryptoStrategyState)
                .values(symbol="BTCUSDT", position_state="FLAT")
                .on_conflict_do_nothing(index_elements=["symbol"])
            )
            row = session.scalar(
                select(CryptoStrategyState).where(CryptoStrategyState.symbol == "BTCUSDT").with_for_update()
            )
            latest = session.scalar(
                select(func.max(CryptoStrategySnapshot.evaluated_at)).where(CryptoStrategySnapshot.symbol == "BTCUSDT")
            )
            if latest and coerce_aware_utc(latest) >= at:
                return None
            if latest and at != coerce_aware_utc(latest) + timedelta(minutes=15):
                raise ValueError("BTC evaluation cannot skip a quarter-hour")
            result = calculate(StrategyState(**values(row)))
            if result is None:
                return None
            state, snapshot = result
            for key in ("position_before", "position_after", "position_delta"):
                if snapshot.get(key) is None:
                    raise ValueError("New snapshots require complete position transitions")
            for key, value in asdict(state).items():
                setattr(row, key, value)
            session.add(CryptoStrategySnapshot(**snapshot))
            return snapshot
