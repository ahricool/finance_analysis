# -*- coding: utf-8 -*-
"""Repositories for holding_source, position_risk_state, and risk_event."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance_analysis.core.time import utc_now  # pragma: allowlist secret
from finance_analysis.database.models.holdings import HoldingSource, PositionRiskState, RiskEvent  # pragma: allowlist secret
from finance_analysis.database.models.notification import Notification  # pragma: allowlist secret
from finance_analysis.database.session import DatabaseManager  # pragma: allowlist secret
from finance_analysis.notification.noise_control import normalize_notification_severity  # pragma: allowlist secret


class HoldingsRepository:
    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or DatabaseManager.get_instance()

    def get_for_uid(self, uid: int) -> HoldingSource | None:
        with self.db.get_session() as session:
            row = session.execute(select(HoldingSource).where(HoldingSource.uid == uid)).scalar_one_or_none()
            if row is not None:
                session.expunge(row)
            return row

    def get_by_id(self, source_id: int, *, uid: int) -> HoldingSource | None:
        with self.db.get_session() as session:
            row = session.get(HoldingSource, source_id)
            if row is None or row.uid != uid:
                return None
            session.expunge(row)
            return row

    def list_enabled(self) -> list[HoldingSource]:
        with self.db.get_session() as session:
            rows = list(
                session.execute(
                    select(HoldingSource).where(
                        HoldingSource.enabled.is_(True),
                        HoldingSource.auth_status == "CONNECTED",
                    )
                ).scalars()
            )
            for row in rows:
                session.expunge(row)
            return rows

    def get_or_create(self, uid: int, *, defaults: dict[str, Any] | None = None) -> HoldingSource:
        def write(session: Session) -> int:
            row = session.execute(select(HoldingSource).where(HoldingSource.uid == uid)).scalar_one_or_none()
            if row is None:
                payload = {"uid": uid, "auth_status": "DISCONNECTED", "risk_policy": {}}
                payload.update(defaults or {})
                row = HoldingSource(**payload)
                session.add(row)
                session.flush()
            return row.id

        source_id = self.db._run_write_transaction("holding_source.get_or_create", write)
        return self.get_by_id(source_id, uid=uid)

    def save(self, source_id: int, *, uid: int, **changes: Any) -> HoldingSource | None:
        def write(session: Session) -> int | None:
            row = session.get(HoldingSource, source_id)
            if row is None or row.uid != uid:
                return None
            for key, value in changes.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
            session.flush()
            return row.id

        updated = self.db._run_write_transaction("holding_source.save", write)
        if updated is None:
            return None
        return self.get_by_id(updated, uid=uid)

    def publish_generation(
        self,
        *,
        source_id: int,
        uid: int,
        expected_config_version: int,
        expected_generation: int,
        new_generation: int,
        content_hash: str,
        sync_status: str,
        error_code: str | None = None,
        published_snapshot: dict | None = None,
    ) -> HoldingSource | None:
        def write(session: Session) -> int | None:
            row = (
                session.execute(
                    select(HoldingSource)
                    .where(
                        HoldingSource.id == source_id,
                        HoldingSource.uid == uid,
                        HoldingSource.config_version == expected_config_version,
                        HoldingSource.published_generation == expected_generation,
                    )
                    .with_for_update()
                )
                .scalar_one_or_none()
            )
            if row is None:
                return None
            row.published_generation = new_generation
            row.content_hash = content_hash
            if published_snapshot is not None:
                row.published_snapshot = published_snapshot
            row.sync_status = sync_status
            row.last_error_code = error_code
            row.last_success_at = utc_now() if sync_status == "OK" else row.last_success_at
            row.last_attempt_at = utc_now()
            row.updated_at = utc_now()
            session.flush()
            return row.id

        updated = self.db._run_write_transaction("holding_source.publish", write)
        return self.get_by_id(updated, uid=uid) if updated else None

    def update_health(self, *, source_id: int, uid: int, **changes: Any) -> HoldingSource | None:
        return self.save(source_id, uid=uid, **changes)

    def lock_source(self, session: Session, *, source_id: int, uid: int) -> HoldingSource | None:
        return session.execute(
            select(HoldingSource)
            .where(HoldingSource.id == source_id, HoldingSource.uid == uid)
            .with_for_update()
        ).scalar_one_or_none()


class PositionRiskStateRepository:
    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or DatabaseManager.get_instance()

    def get(self, session: Session, *, source_id: int, account_id: str, position_id: str) -> PositionRiskState | None:
        return session.execute(
            select(PositionRiskState).where(
                PositionRiskState.source_id == source_id,
                PositionRiskState.account_id == account_id,
                PositionRiskState.position_id == position_id,
            )
        ).scalar_one_or_none()

    def lock_many(
        self,
        session: Session,
        *,
        source_id: int,
        keys: Iterable[tuple[str, str]],
    ) -> dict[tuple[str, str], PositionRiskState]:
        ordered = sorted(set(keys))
        found: dict[tuple[str, str], PositionRiskState] = {}
        for account_id, position_id in ordered:
            row = session.execute(
                select(PositionRiskState)
                .where(
                    PositionRiskState.source_id == source_id,
                    PositionRiskState.account_id == account_id,
                    PositionRiskState.position_id == position_id,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if row is not None:
                found[(account_id, position_id)] = row
        return found

    def get_for_source(self, *, uid: int, source_id: int) -> list[PositionRiskState]:
        with self.db.get_session() as session:
            rows = list(
                session.execute(
                    select(PositionRiskState).where(
                        PositionRiskState.uid == uid,
                        PositionRiskState.source_id == source_id,
                    )
                ).scalars()
            )
            for row in rows:
                session.expunge(row)
            return rows


class RiskEventRepository:
    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or DatabaseManager.get_instance()

    def list_for_source(self, *, uid: int, source_id: int, limit: int = 100) -> list[RiskEvent]:
        with self.db.get_session() as session:
            rows = list(
                session.execute(
                    select(RiskEvent)
                    .where(RiskEvent.uid == uid, RiskEvent.source_id == source_id)
                    .order_by(RiskEvent.id.desc())
                    .limit(limit)
                ).scalars()
            )
            for row in rows:
                session.expunge(row)
            return rows

    def has_dedupe(self, session: Session, *, uid: int, dedupe_key: str) -> bool:
        return (
            session.execute(
                select(RiskEvent.id).where(RiskEvent.uid == uid, RiskEvent.dedupe_key == dedupe_key)
            ).scalar_one_or_none()
            is not None
        )

    def add(
        self,
        session: Session,
        *,
        uid: int,
        source_id: int,
        account_id: str,
        position_id: str,
        event_type: str,
        rule_version: str,
        action: str,
        dedupe_key: str,
        leg_id: str | None = None,
        input_version: str | None = None,
        episode_id: str | None = None,
        plan_revision: int | None = None,
        trigger_quantity=None,
        target_quantity=None,
        evidence: dict | None = None,
        data_time: datetime | None = None,
        notification_id: int | None = None,
        push_status: str = "PENDING",
    ) -> RiskEvent:
        row = RiskEvent(
            uid=uid,
            source_id=source_id,
            account_id=account_id,
            position_id=position_id,
            leg_id=leg_id,
            event_type=event_type,
            rule_version=rule_version,
            input_version=input_version,
            episode_id=episode_id,
            plan_revision=plan_revision,
            action=action,
            trigger_quantity=trigger_quantity,
            target_quantity=target_quantity,
            evidence=evidence or {},
            data_time=data_time,
            dedupe_key=dedupe_key,
            notification_id=notification_id,
            push_status=push_status,
        )
        session.add(row)
        session.flush()
        return row

    def mark_push_status(self, session: Session, *, notification_id: int, push_status: str) -> None:
        rows = list(
            session.execute(select(RiskEvent).where(RiskEvent.notification_id == notification_id)).scalars()
        )
        for row in rows:
            row.push_status = push_status
        session.flush()

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
