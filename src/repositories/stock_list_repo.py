# -*- coding: utf-8 -*-
"""Repository for stock_list (持仓股) CRUD operations."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import select

from src.services.market_type_utils import normalize_market_type
from sqlalchemy.orm import Session

from src.storage import DatabaseManager, StockHolding


def get_db() -> DatabaseManager:
    return DatabaseManager.get_instance()


class StockListRepo:
    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or get_db()

    # ── Read ──────────────────────────────────────────────────────────────────

    def list_all(self, uid: Optional[int] = None) -> List[StockHolding]:
        with self.db.get_session() as session:
            stmt = select(StockHolding).order_by(StockHolding.created_at)
            if uid is not None:
                stmt = stmt.where(StockHolding.uid == uid)
            return session.execute(stmt).scalars().all()

    def get_by_id(self, item_id: int, uid: Optional[int] = None) -> Optional[StockHolding]:
        with self.db.get_session() as session:
            obj = session.get(StockHolding, item_id)
            if obj is None:
                return None
            if uid is not None and obj.uid != uid:
                return None
            return obj

    def get_by_code(self, code: str, uid: Optional[int] = None) -> Optional[StockHolding]:
        with self.db.get_session() as session:
            stmt = select(StockHolding).where(StockHolding.code == code.upper())
            if uid is not None:
                stmt = stmt.where(StockHolding.uid == uid)
            return session.execute(stmt).scalars().first()

    def get_codes(self, uid: Optional[int] = None) -> List[str]:
        """Return all stock codes in the holdings list (used as analysis targets)."""
        with self.db.get_session() as session:
            stmt = select(StockHolding.code)
            if uid is not None:
                stmt = stmt.where(StockHolding.uid == uid)
            return list(session.execute(stmt).scalars().all())

    # ── Write ─────────────────────────────────────────────────────────────────

    def create(
        self,
        *,
        uid: int,
        code: str,
        name: Optional[str] = None,
        quantity: int = 0,
        notes: Optional[str] = None,
        market_type: Optional[str] = None,
    ) -> StockHolding:
        item = StockHolding(
            uid=uid,
            code=code.upper().strip(),
            name=(name or "").strip() or None,
            quantity=max(0, quantity),
            market_type=normalize_market_type(market_type, code),
            notes=(notes or "").strip() or None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        def _write(session: Session) -> StockHolding:
            session.add(item)
            session.flush()
            session.refresh(item)
            return item

        return self.db._run_write_transaction("stock_list.create", _write)

    def update(
        self,
        item_id: int,
        *,
        uid: Optional[int] = None,
        name: Optional[str] = None,
        quantity: Optional[int] = None,
        notes: Optional[str] = None,
        market_type: Optional[str] = None,
    ) -> Optional[StockHolding]:
        def _write(session: Session) -> Optional[StockHolding]:
            obj = session.get(StockHolding, item_id)
            if obj is None:
                return None
            if uid is not None and obj.uid != uid:
                return None
            if name is not None:
                obj.name = name.strip() or None
            if quantity is not None:
                obj.quantity = max(0, quantity)
            if notes is not None:
                obj.notes = notes.strip() or None
            if market_type is not None:
                obj.market_type = normalize_market_type(market_type, obj.code)
            obj.updated_at = datetime.now()
            session.flush()
            session.refresh(obj)
            return obj

        return self.db._run_write_transaction("stock_list.update", _write)

    def delete(self, item_id: int, uid: Optional[int] = None) -> bool:
        def _write(session: Session) -> bool:
            obj = session.get(StockHolding, item_id)
            if obj is None:
                return False
            if uid is not None and obj.uid != uid:
                return False
            session.delete(obj)
            return True

        return self.db._run_write_transaction("stock_list.delete", _write)
