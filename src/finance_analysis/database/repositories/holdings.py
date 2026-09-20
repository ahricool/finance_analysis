# -*- coding: utf-8 -*-
"""Repository for holding_source (Google Sheet secondary input)."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance_analysis.core.time import utc_now  # pragma: allowlist secret
from finance_analysis.database.models.holdings import HoldingSource  # pragma: allowlist secret
from finance_analysis.database.session import DatabaseManager  # pragma: allowlist secret


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
