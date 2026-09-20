# -*- coding: utf-8 -*-
"""Repositories for DB-authoritative portfolio accounts, positions, lots, and operations."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance_analysis.core.time import utc_now  # pragma: allowlist secret
from finance_analysis.database.models.portfolio import (  # pragma: allowlist secret
    CashOperation,
    PortfolioAccount,
    PortfolioPosition,
    PositionLot,
    TradeOperation,
)
from finance_analysis.database.session import DatabaseManager  # pragma: allowlist secret

DEFAULT_ACCOUNT_NAMES = {"CN": "A股账户", "US": "美股账户"}


def _dec(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class PortfolioRepository:
    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or DatabaseManager.get_instance()

    def run_write(self, name: str, operation):
        return self.db._run_write_transaction(name, operation)

    def lock_account(self, session: Session, *, uid: int, account_id: int) -> PortfolioAccount | None:
        return session.execute(
            select(PortfolioAccount)
            .where(PortfolioAccount.id == account_id, PortfolioAccount.uid == uid)
            .with_for_update()
        ).scalar_one_or_none()

    def lock_position(self, session: Session, *, uid: int, position_id: int) -> PortfolioPosition | None:
        return session.execute(
            select(PortfolioPosition)
            .where(PortfolioPosition.id == position_id, PortfolioPosition.uid == uid)
            .with_for_update()
        ).scalar_one_or_none()

    def get_account(self, session: Session, *, uid: int, account_id: int) -> PortfolioAccount | None:
        row = session.get(PortfolioAccount, account_id)
        if row is None or row.uid != uid:
            return None
        return row

    def get_account_by_market(self, session: Session, *, uid: int, market: str) -> PortfolioAccount | None:
        return session.execute(
            select(PortfolioAccount)
            .where(
                PortfolioAccount.uid == uid,
                PortfolioAccount.market == market,
                PortfolioAccount.name == DEFAULT_ACCOUNT_NAMES[market],
            )
        ).scalar_one_or_none()

    def ensure_default_accounts(self, session: Session, uid: int) -> list[PortfolioAccount]:
        accounts: list[PortfolioAccount] = []
        now = utc_now()
        for market, name in DEFAULT_ACCOUNT_NAMES.items():
            row = self.get_account_by_market(session, uid=uid, market=market)
            if row is None:
                row = PortfolioAccount(uid=uid, name=name, market=market, cash=Decimal("0"), created_at=now, updated_at=now)
                session.add(row)
                session.flush()
            accounts.append(row)
        return accounts

    def list_accounts(self, session: Session, *, uid: int, market: str | None = None) -> list[PortfolioAccount]:
        query = select(PortfolioAccount).where(PortfolioAccount.uid == uid)
        if market:
            query = query.where(PortfolioAccount.market == market)
        return list(session.execute(query.order_by(PortfolioAccount.market, PortfolioAccount.id)).scalars())

    def get_open_position(self, session: Session, *, account_id: int, symbol: str) -> PortfolioPosition | None:
        return session.execute(
            select(PortfolioPosition).where(
                PortfolioPosition.account_id == account_id,
                PortfolioPosition.symbol == symbol,
                PortfolioPosition.closed_at.is_(None),
            )
        ).scalar_one_or_none()

    def list_open_positions(
        self,
        session: Session,
        *,
        uid: int,
        market: str | None = None,
        account_id: int | None = None,
    ) -> list[PortfolioPosition]:
        query = select(PortfolioPosition).where(
            PortfolioPosition.uid == uid,
            PortfolioPosition.closed_at.is_(None),
            PortfolioPosition.quantity > 0,
        )
        if market:
            query = query.where(PortfolioPosition.market == market)
        if account_id is not None:
            query = query.where(PortfolioPosition.account_id == account_id)
        return list(session.execute(query.order_by(PortfolioPosition.symbol, PortfolioPosition.id)).scalars())

    def list_uids_with_open_positions(self, session: Session, *, market: str | None = None) -> list[int]:
        query = select(PortfolioPosition.uid).where(
            PortfolioPosition.closed_at.is_(None),
            PortfolioPosition.quantity > 0,
        )
        if market:
            query = query.where(PortfolioPosition.market == market)
        return list(session.execute(query.distinct()).scalars())

    def get_position(self, session: Session, *, uid: int, position_id: int) -> PortfolioPosition | None:
        row = session.get(PortfolioPosition, position_id)
        if row is None or row.uid != uid:
            return None
        return row

    def list_lots(self, session: Session, *, position_ids: Iterable[int]) -> dict[int, list[PositionLot]]:
        ids = sorted(set(position_ids))
        if not ids:
            return {}
        rows = list(session.execute(select(PositionLot).where(PositionLot.position_id.in_(ids))).scalars())
        grouped: dict[int, list[PositionLot]] = {item: [] for item in ids}
        for row in rows:
            grouped.setdefault(row.position_id, []).append(row)
        for lots in grouped.values():
            lots.sort(key=lambda item: (item.entry_time, item.id))
        return grouped

    def list_operations(
        self,
        session: Session,
        *,
        uid: int,
        position_id: int,
        limit: int = 200,
    ) -> list[TradeOperation]:
        return list(
            session.execute(
                select(TradeOperation)
                .where(TradeOperation.uid == uid, TradeOperation.position_id == position_id)
                .order_by(TradeOperation.executed_at.desc(), TradeOperation.id.desc())
                .limit(limit)
            ).scalars()
        )

    def list_operations_for_symbols(
        self,
        session: Session,
        *,
        uid: int,
        symbols: Iterable[str],
    ) -> list[TradeOperation]:
        codes = sorted({item for item in symbols if item})
        if not codes:
            return []
        return list(
            session.execute(
                select(TradeOperation)
                .where(TradeOperation.uid == uid, TradeOperation.symbol.in_(codes))
                .order_by(TradeOperation.executed_at.asc(), TradeOperation.id.asc())
            ).scalars()
        )

    def add_position(self, session: Session, **payload: Any) -> PortfolioPosition:
        row = PortfolioPosition(**payload)
        session.add(row)
        session.flush()
        return row

    def add_lot(self, session: Session, **payload: Any) -> PositionLot:
        row = PositionLot(**payload)
        session.add(row)
        session.flush()
        return row

    def add_trade(self, session: Session, **payload: Any) -> TradeOperation:
        row = TradeOperation(**payload)
        session.add(row)
        session.flush()
        return row

    def add_cash(self, session: Session, **payload: Any) -> CashOperation:
        row = CashOperation(**payload)
        session.add(row)
        session.flush()
        return row


__all__ = ["DEFAULT_ACCOUNT_NAMES", "PortfolioRepository", "_dec"]
