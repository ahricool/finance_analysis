# -*- coding: utf-8 -*-
"""Repositories for Trade Engine strategy state and signals."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance_analysis.core.time import utc_now  # pragma: allowlist secret
from finance_analysis.database.models.notification import Notification  # pragma: allowlist secret
from finance_analysis.database.models.trade_engine import TradeSignalRow, TradeStrategyState  # pragma: allowlist secret
from finance_analysis.database.session import DatabaseManager  # pragma: allowlist secret
from finance_analysis.notification.noise_control import normalize_notification_severity  # pragma: allowlist secret


class TradeEngineRepository:
    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or DatabaseManager.get_instance()

    def get_state(
        self,
        session: Session,
        *,
        uid: int,
        account_id: str,
        position_id: str,
        strategy_key: str,
    ) -> TradeStrategyState | None:
        return session.execute(
            select(TradeStrategyState).where(
                TradeStrategyState.uid == uid,
                TradeStrategyState.account_id == account_id,
                TradeStrategyState.position_id == position_id,
                TradeStrategyState.strategy_key == strategy_key,
            )
        ).scalar_one_or_none()

    def upsert_state(
        self,
        session: Session,
        *,
        uid: int,
        account_id: str,
        position_id: str,
        strategy_key: str,
        strategy_version: str,
        state: dict[str, Any],
        evaluated_at: datetime,
    ) -> TradeStrategyState:
        row = self.get_state(
            session,
            uid=uid,
            account_id=account_id,
            position_id=position_id,
            strategy_key=strategy_key,
        )
        now = utc_now()
        if row is None:
            row = TradeStrategyState(
                uid=uid,
                account_id=account_id,
                position_id=position_id,
                strategy_key=strategy_key,
                strategy_version=strategy_version,
                state=state,
                last_evaluated_at=evaluated_at,
                updated_at=now,
            )
            session.add(row)
        else:
            row.strategy_version = strategy_version
            row.state = state
            row.last_evaluated_at = evaluated_at
            row.updated_at = now
        session.flush()
        return row

    def list_states(self, session: Session, *, uid: int, market: str | None = None) -> list[TradeStrategyState]:
        query = select(TradeStrategyState).where(TradeStrategyState.uid == uid)
        rows = list(session.execute(query).scalars())
        del market
        return rows

    def has_signal(self, session: Session, *, uid: int, signal_key: str) -> bool:
        return (
            session.execute(
                select(TradeSignalRow.id).where(TradeSignalRow.uid == uid, TradeSignalRow.signal_key == signal_key)
            ).scalar_one_or_none()
            is not None
        )

    def add_signal(self, session: Session, **payload: Any) -> TradeSignalRow:
        row = TradeSignalRow(**payload)
        session.add(row)
        session.flush()
        return row

    def list_signals(
        self,
        session: Session,
        *,
        uid: int,
        market: str | None = None,
        position_id: str | None = None,
        limit: int = 100,
    ) -> list[TradeSignalRow]:
        query = select(TradeSignalRow).where(TradeSignalRow.uid == uid)
        if market:
            query = query.where(TradeSignalRow.market == market)
        if position_id:
            query = query.where(TradeSignalRow.position_id == position_id)
        return list(session.execute(query.order_by(TradeSignalRow.id.desc()).limit(limit)).scalars())

    def create_notification(
        self,
        session: Session,
        *,
        uid: int,
        title: str,
        content: str,
        route_type: str = "alert",
        severity: str | None = None,
    ) -> int:
        row = Notification(
            uid=uid,
            title=title[:300],
            content=content,
            route_type=route_type,
            severity=normalize_notification_severity(route_type, severity),
        )
        session.add(row)
        session.flush()
        return row.id


__all__ = ["TradeEngineRepository"]
