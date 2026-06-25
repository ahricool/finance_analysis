# -*- coding: utf-8 -*-
"""Repository for stock_list (持仓股) CRUD operations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional

from sqlalchemy import select

from finance_analysis.stocks.markets import normalize_market_type
from sqlalchemy.orm import Session

from finance_analysis.database.session import DatabaseManager
from finance_analysis.database.models import StockHolding
from finance_analysis.core.time import utc_now

ZERO_DECIMAL = Decimal("0")
_UNSET = object()


def get_db() -> DatabaseManager:
    return DatabaseManager.get_instance()


def _to_non_negative_decimal(value: Decimal | int | str | None, *, field_name: str) -> Decimal:
    if value is None:
        return ZERO_DECIMAL
    parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    if parsed < ZERO_DECIMAL:
        raise ValueError(f"{field_name} must be greater than or equal to 0")
    return parsed


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

    def get_by_code(
        self,
        code: str,
        uid: Optional[int] = None,
        market_type: Optional[str] = None,
    ) -> Optional[StockHolding]:
        with self.db.get_session() as session:
            stmt = select(StockHolding).where(StockHolding.code == code.upper())
            if uid is not None:
                stmt = stmt.where(StockHolding.uid == uid)
            if market_type is not None:
                stmt = stmt.where(StockHolding.market_type == normalize_market_type(market_type, code))
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
        quantity: Decimal | int | str = ZERO_DECIMAL,
        avg_cost: Optional[Decimal | int | str] = None,
        opened_at: Optional[datetime] = None,
        notes: Optional[str] = None,
        market_type: Optional[str] = None,
    ) -> StockHolding:
        normalized_market = normalize_market_type(market_type, code)
        item = StockHolding(
            uid=uid,
            code=code.upper().strip(),
            name=(name or "").strip() or None,
            quantity=_to_non_negative_decimal(quantity, field_name="quantity"),
            avg_cost=(
                _to_non_negative_decimal(avg_cost, field_name="avg_cost")
                if avg_cost is not None
                else None
            ),
            opened_at=opened_at,
            market_type=normalized_market,
            notes=(notes or "").strip() or None,
            created_at=utc_now(),
            updated_at=utc_now(),
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
        quantity: Optional[Decimal | int | str] = None,
        avg_cost: Any = _UNSET,
        opened_at: Any = _UNSET,
        notes: Optional[str] = None,
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
                obj.quantity = _to_non_negative_decimal(quantity, field_name="quantity")
            if avg_cost is not _UNSET:
                obj.avg_cost = (
                    _to_non_negative_decimal(avg_cost, field_name="avg_cost")
                    if avg_cost is not None
                    else None
                )
            if opened_at is not _UNSET:
                obj.opened_at = opened_at
            if notes is not None:
                obj.notes = notes.strip() or None
            obj.updated_at = utc_now()
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
