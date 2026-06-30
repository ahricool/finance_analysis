"""Repository for bounded, incremental signal evaluation queries."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import and_, func, or_, select

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
        signal_version: str = "v1",
        direction: str = "neutral",
    ) -> Signal:
        normalized_direction = direction.strip().lower()
        if normalized_direction not in {"bullish", "bearish", "sideways", "neutral"}:
            normalized_direction = "neutral"
        row = Signal(
            market=market.upper(),
            code=code,
            name=name,
            signal_type=signal_type,
            signal_version=signal_version.strip() or "v1",
            direction=normalized_direction,
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

    def list_signals(
        self,
        *,
        limit: int,
        offset: int,
        market: str | None = None,
        direction: str | None = None,
        signal_type: str | None = None,
        keyword: str | None = None,
        signal_at_from: datetime | None = None,
        signal_at_to: datetime | None = None,
    ) -> list[Signal]:
        conditions = self._query_conditions(
            market=market,
            direction=direction,
            signal_type=signal_type,
            keyword=keyword,
            signal_at_from=signal_at_from,
            signal_at_to=signal_at_to,
        )
        statement = select(Signal)
        if conditions:
            statement = statement.where(and_(*conditions))
        statement = statement.order_by(Signal.signal_at.desc(), Signal.id.desc())
        statement = statement.offset(max(0, int(offset))).limit(max(1, int(limit)))
        with self.db.get_session() as session:
            rows = session.execute(statement).scalars().all()
            for row in rows:
                session.expunge(row)
            return list(rows)

    def count_signals(
        self,
        *,
        market: str | None = None,
        direction: str | None = None,
        signal_type: str | None = None,
        keyword: str | None = None,
        signal_at_from: datetime | None = None,
        signal_at_to: datetime | None = None,
    ) -> int:
        conditions = self._query_conditions(
            market=market,
            direction=direction,
            signal_type=signal_type,
            keyword=keyword,
            signal_at_from=signal_at_from,
            signal_at_to=signal_at_to,
        )
        statement = select(func.count()).select_from(Signal)
        if conditions:
            statement = statement.where(and_(*conditions))
        with self.db.get_session() as session:
            return int(session.execute(statement).scalar_one())

    def get_by_id(self, signal_id: int) -> Signal | None:
        with self.db.get_session() as session:
            row = session.get(Signal, signal_id)
            if row is not None:
                session.expunge(row)
            return row

    @staticmethod
    def _query_conditions(
        *,
        market: str | None,
        direction: str | None,
        signal_type: str | None,
        keyword: str | None,
        signal_at_from: datetime | None,
        signal_at_to: datetime | None,
    ) -> list[Any]:
        conditions: list[Any] = []
        if market:
            conditions.append(Signal.market == market.upper())
        if direction:
            conditions.append(Signal.direction == direction.lower())
        if signal_type and signal_type.strip():
            conditions.append(Signal.signal_type == signal_type.strip())
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            conditions.append(or_(Signal.code.ilike(pattern), Signal.name.ilike(pattern)))
        if signal_at_from is not None:
            conditions.append(Signal.signal_at >= signal_at_from)
        if signal_at_to is not None:
            conditions.append(Signal.signal_at <= signal_at_to)
        return conditions

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
