# -*- coding: utf-8 -*-
"""Repositories for Trade Engine LLM state and official signals."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance_analysis.market_review.trading_calendar import MARKET_TIMEZONE
from finance_analysis.core.time import utc_now  # pragma: allowlist secret
from finance_analysis.database.models.notification import Notification  # pragma: allowlist secret
from finance_analysis.database.models.trade_engine import TradeLLMState, TradeSignalRow  # pragma: allowlist secret
from finance_analysis.database.session import DatabaseManager  # pragma: allowlist secret
from finance_analysis.notification.noise_control import normalize_notification_severity  # pragma: allowlist secret


class TradeEngineRepository:
    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or DatabaseManager.get_instance()

    def get_llm_state(self, session: Session, *, uid: int, market: str) -> TradeLLMState | None:
        return session.execute(
            select(TradeLLMState).where(TradeLLMState.uid == uid, TradeLLMState.market == market)
        ).scalar_one_or_none()

    def upsert_llm_state(
        self,
        session: Session,
        *,
        uid: int,
        market: str,
        summary: str,
        last_decision: dict[str, Any],
        decided_at: datetime,
    ) -> TradeLLMState:
        row = self.get_llm_state(session, uid=uid, market=market)
        now = utc_now()
        if row is None:
            row = TradeLLMState(
                uid=uid,
                market=market,
                summary=summary,
                last_decision=last_decision,
                last_decision_at=decided_at,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.summary = summary
            row.last_decision = last_decision
            row.last_decision_at = decided_at
            row.updated_at = now
        session.flush()
        return row

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

    def notified_actions_for_date(
        self, session: Session, *, uid: int, market: str, local_date: date,
    ) -> set[tuple[str, str]]:
        zone = ZoneInfo(MARKET_TIMEZONE[market.lower()])
        start = datetime.combine(local_date, time.min, tzinfo=zone).astimezone(timezone.utc)
        end = datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=zone).astimezone(timezone.utc)
        return set(session.execute(
            select(TradeSignalRow.symbol, TradeSignalRow.action).where(
                TradeSignalRow.uid == uid,
                TradeSignalRow.market == market,
                TradeSignalRow.notification_id.is_not(None),
                TradeSignalRow.evaluated_at >= start,
                TradeSignalRow.evaluated_at < end,
            ).distinct()
        ).all())

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
