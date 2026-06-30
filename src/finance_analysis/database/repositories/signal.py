"""Repository for bounded, incremental signal evaluation queries."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import and_, or_, select

from finance_analysis.database.models.signal import Signal
from finance_analysis.database.session import DatabaseManager


class SignalRepository:
    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()

    def create(
        self,
        *,
        market: str,
        code: str,
        price: float,
        signal_at: datetime,
        evaluation: dict[str, Any],
        name: str | None = None,
        signal_type: str | None = None,
    ) -> Signal:
        row = Signal(
            market=market.upper(),
            code=code,
            name=name,
            signal_type=signal_type,
            price=price,
            signal_at=signal_at,
            evaluation=dict(evaluation),
        )
        with self.db.get_session() as session:
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
        return row

    def list_for_evaluation(
        self,
        *,
        market: str,
        signal_at_from: datetime,
        limit: int,
        cursor: tuple[datetime, int] | None = None,
    ) -> list[Signal]:
        """Return one stable keyset page from the requested market and 15-day window."""
        conditions = [Signal.market == market.upper(), Signal.signal_at >= signal_at_from]
        if cursor is not None:
            cursor_time, cursor_id = cursor
            conditions.append(
                or_(
                    Signal.signal_at > cursor_time,
                    and_(Signal.signal_at == cursor_time, Signal.id > cursor_id),
                )
            )
        with self.db.get_session() as session:
            rows = session.execute(
                select(Signal)
                .where(and_(*conditions))
                .order_by(Signal.signal_at, Signal.id)
                .limit(max(1, int(limit)))
            ).scalars().all()
            for row in rows:
                session.expunge(row)
            return list(rows)

    def update_evaluation(self, signal_id: int, evaluation: dict[str, Any]) -> None:
        with self.db.get_session() as session:
            row = session.get(Signal, signal_id)
            if row is None:
                raise LookupError(f"Signal {signal_id} no longer exists")
            merged = dict(row.evaluation or {})
            for period, result in evaluation.items():
                merged.setdefault(period, result)
            row.evaluation = merged
            session.commit()


__all__ = ["SignalRepository"]
