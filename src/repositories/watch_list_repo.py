# -*- coding: utf-8 -*-
"""Repository for watch_list (自选股) CRUD operations."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage import DatabaseManager, WatchListItem


def get_db() -> DatabaseManager:
    return DatabaseManager.get_instance()


class WatchListRepo:
    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or get_db()

    # ── Read ──────────────────────────────────────────────────────────────────

    def list_all(self) -> List[WatchListItem]:
        with self.db.get_session() as session:
            items = list(
                session.execute(
                    select(WatchListItem).order_by(WatchListItem.created_at)
                ).scalars().all()
            )
            # Expunge so instances survive session commit/close without
            # expire-on-commit leaving attributes unloaded (DetachedInstanceError).
            for row in items:
                session.expunge(row)
            return items

    def get_by_id(self, item_id: int) -> Optional[WatchListItem]:
        with self.db.get_session() as session:
            obj = session.get(WatchListItem, item_id)
            if obj is not None:
                session.expunge(obj)
            return obj

    def get_by_code(self, code: str) -> Optional[WatchListItem]:
        with self.db.get_session() as session:
            obj = session.execute(
                select(WatchListItem).where(WatchListItem.code == code.upper())
            ).scalar_one_or_none()
            if obj is not None:
                session.expunge(obj)
            return obj

    def get_codes(self) -> List[str]:
        """Return all stock codes in the watch list."""
        with self.db.get_session() as session:
            return list(
                session.execute(select(WatchListItem.code)).scalars().all()
            )

    # ── Write ─────────────────────────────────────────────────────────────────

    def create(self, code: str, name: Optional[str] = None, notes: Optional[str] = None) -> WatchListItem:
        item = WatchListItem(
            code=code.upper().strip(),
            name=(name or "").strip() or None,
            notes=(notes or "").strip() or None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        def _write(session: Session) -> WatchListItem:
            session.add(item)
            session.flush()
            session.refresh(item)
            session.expunge(item)
            return item

        return self.db._run_write_transaction("watch_list.create", _write)

    def update(
        self,
        item_id: int,
        name: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[WatchListItem]:
        def _write(session: Session) -> Optional[WatchListItem]:
            obj = session.get(WatchListItem, item_id)
            if obj is None:
                return None
            if name is not None:
                obj.name = name.strip() or None
            if notes is not None:
                obj.notes = notes.strip() or None
            obj.updated_at = datetime.now()
            session.flush()
            session.refresh(obj)
            session.expunge(obj)
            return obj

        return self.db._run_write_transaction("watch_list.update", _write)

    def delete(self, item_id: int) -> bool:
        def _write(session: Session) -> bool:
            obj = session.get(WatchListItem, item_id)
            if obj is None:
                return False
            session.delete(obj)
            return True

        return self.db._run_write_transaction("watch_list.delete", _write)
