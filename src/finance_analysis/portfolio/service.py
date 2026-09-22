# -*- coding: utf-8 -*-
"""Transactional BUY/SELL and cash adjustments for DB portfolio facts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from finance_analysis.portfolio.receipts import request_hash

from sqlalchemy.orm import Session

from finance_analysis.core.time import coerce_aware_utc, utc_now  # pragma: allowlist secret
from finance_analysis.database.models.portfolio import PortfolioPosition, PositionLot  # pragma: allowlist secret
from finance_analysis.database.repositories.portfolio import (  # pragma: allowlist secret
    PortfolioRepository,
    _dec,
)
from finance_analysis.integrations.market_data.normalizer import canonical_symbol, infer_market  # pragma: allowlist secret
from finance_analysis.portfolio.errors import (  # pragma: allowlist secret
    InsufficientQuantityError,
    PortfolioError,
    PositionClosedError,
    UnsupportedAssetError,
)

SUPPORTED_MARKETS = {"CN", "US"}
SUPPORTED_ASSETS = {"STOCK", "ETF"}


def _qty(value: Decimal | str | int | float) -> Decimal:
    quantity = _dec(value)
    if quantity <= 0:
        raise PortfolioError("数量必须大于 0")
    return quantity


def _price(value: Decimal | str | int | float) -> Decimal:
    price = _dec(value)
    if price <= 0:
        raise PortfolioError("价格必须大于 0")
    return price


def _when(value: datetime | None) -> datetime:
    current = coerce_aware_utc(value) if value is not None else utc_now()
    if current is None:
        return utc_now()
    return current


def _weighted_average(lots: list[PositionLot]) -> Decimal:
    remaining = [lot for lot in lots if _dec(lot.remaining_quantity) > 0]
    total = sum((_dec(lot.remaining_quantity) for lot in remaining), start=Decimal("0"))
    if total <= 0:
        return Decimal("0")
    weighted = sum((_dec(lot.remaining_quantity) * _dec(lot.entry_price) for lot in remaining), start=Decimal("0"))
    return weighted / total


def _sell_order(lots: list[PositionLot]) -> list[PositionLot]:
    open_lots = [lot for lot in lots if _dec(lot.remaining_quantity) > 0]
    return sorted(
        open_lots,
        key=lambda lot: (0 if lot.role == "ADDON" else 1, -lot.entry_time.timestamp(), -int(lot.id or 0)),
    )


class PortfolioService:
    def __init__(self, repository: PortfolioRepository | None = None) -> None:
        self.repository = repository or PortfolioRepository()

    def _mutate(self, kind, uid, operation_id, payload, write):
        if operation_id is None:  # Internal callers may explicitly perform a fresh operation.
            return self.repository.run_write(f"portfolio.{kind}", write)
        operation_id = str(UUID(str(operation_id)))
        return self.repository.run_idempotent_write(
            f"portfolio.{kind}", uid, operation_id, request_hash({"kind": kind, **payload}), write,
        )

    def ensure_accounts(self, uid: int) -> list[dict[str, Any]]:
        def write(session: Session):
            return [self._account_view(row) for row in self.repository.ensure_default_accounts(session, uid)]

        return self.repository.run_write("portfolio.ensure_accounts", write)

    def list_accounts(self, uid: int, *, market: str | None = None) -> list[dict[str, Any]]:
        self.ensure_accounts(uid)
        with self.repository.db.get_session() as session:
            return [self._account_view(row) for row in self.repository.list_accounts(session, uid=uid, market=market)]

    def set_cash(
        self, uid: int, *, account_id: int, amount: Decimal | str | int | float, operation_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            value = _dec(amount)
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise PortfolioError("现金必须是非负有限金额") from exc
        if not value.is_finite() or value < 0 or value >= Decimal("1e20"):
            raise PortfolioError("现金必须是非负有限金额且小于 1e20")

        def write(session: Session):
            account = self.repository.lock_account(session, uid=uid, account_id=account_id)
            if account is None:
                raise PortfolioError("账户不存在")
            account.cash = value
            account.updated_at = utc_now()
            session.flush()
            return self._account_view(account)

        return self._mutate("cash", uid, operation_id, {"account_id": account_id, "amount": str(value.normalize())}, write)

    def buy(
        self,
        uid: int,
        *,
        account_id: int,
        symbol: str,
        quantity: Decimal | str | int | float,
        price: Decimal | str | int | float,
        executed_at: datetime | None = None,
        note: str | None = None,
        asset_type: str = "STOCK",
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        qty = _qty(quantity)
        px = _price(price)
        when = _when(executed_at)
        asset = (asset_type or "STOCK").upper()
        if asset not in SUPPORTED_ASSETS:
            raise UnsupportedAssetError()
        canonical = canonical_symbol(symbol)
        market = infer_market(canonical).value
        if market not in SUPPORTED_MARKETS:
            raise PortfolioError("当前账户仅支持 A 股与美股")

        def write(session: Session):
            account = self.repository.lock_account(session, uid=uid, account_id=account_id)
            if account is None:
                raise PortfolioError("账户不存在")
            if account.market != market:
                raise PortfolioError("标的市场与账户市场不一致")
            instrument = self.repository.get_instrument(session, symbol=canonical)
            if instrument is None:
                raise PortfolioError("请选择证券主数据中存在的股票或 ETF")
            if instrument.market != market:
                raise PortfolioError("标的市场与账户市场不一致")
            if instrument.instrument_type not in SUPPORTED_ASSETS:
                raise UnsupportedAssetError()
            position = self.repository.get_open_position(session, account_id=account.id, symbol=canonical)
            if position is None:
                position = self.repository.add_position(
                    session,
                    uid=uid,
                    account_id=account.id,
                    market=market,
                    symbol=canonical,
                    asset_type=instrument.instrument_type,
                    quantity=Decimal("0"),
                    average_cost=Decimal("0"),
                    opened_at=when,
                    closed_at=None,
                    updated_at=when,
                )
            lots = self.repository.list_lots(session, position_ids=[position.id]).get(position.id, [])
            role = "CORE" if _dec(position.quantity) <= 0 else "ADDON"
            self.repository.add_lot(
                session,
                position_id=position.id,
                role=role,
                entry_price=px,
                entry_time=when,
                original_quantity=qty,
                remaining_quantity=qty,
                created_at=when,
                closed_at=None,
            )
            self.repository.add_trade(
                session,
                uid=uid,
                account_id=account.id,
                position_id=position.id,
                market=market,
                symbol=canonical,
                side="BUY",
                quantity=qty,
                price=px,
                executed_at=when,
                created_at=utc_now(),
                note=note,
            )
            lots = self.repository.list_lots(session, position_ids=[position.id]).get(position.id, [])
            position.quantity = _dec(position.quantity) + qty
            position.average_cost = _weighted_average(lots)
            position.closed_at = None
            position.updated_at = when
            session.flush()
            return self._position_view(session, position)

        return self._mutate("buy", uid, operation_id, {
            "account_id": account_id, "symbol": canonical, "quantity": str(qty.normalize()),
            "price": str(px.normalize()), "asset_type": asset, "note": note,
            "executed_at": _when(executed_at) if executed_at is not None else None,
        }, write)

    def sell(
        self,
        uid: int,
        *,
        position_id: int,
        quantity: Decimal | str | int | float,
        price: Decimal | str | int | float,
        executed_at: datetime | None = None,
        note: str | None = None,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        qty = _qty(quantity)
        px = _price(price)
        when = _when(executed_at)

        def write(session: Session):
            position = self.repository.lock_position(session, uid=uid, position_id=position_id)
            if position is None:
                raise PortfolioError("持仓不存在")
            if position.closed_at is not None or _dec(position.quantity) <= 0:
                raise PositionClosedError()
            current = _dec(position.quantity)
            if qty > current:
                raise InsufficientQuantityError()
            account = self.repository.lock_account(session, uid=uid, account_id=position.account_id)
            if account is None:
                raise PortfolioError("账户不存在")
            lots = self.repository.list_lots(session, position_ids=[position.id]).get(position.id, [])
            remaining_to_sell = qty
            for lot in _sell_order(lots):
                if remaining_to_sell <= 0:
                    break
                available = _dec(lot.remaining_quantity)
                take = min(available, remaining_to_sell)
                lot.remaining_quantity = available - take
                if _dec(lot.remaining_quantity) <= 0:
                    lot.remaining_quantity = Decimal("0")
                    lot.closed_at = when
                remaining_to_sell -= take
            if remaining_to_sell > 0:
                raise InsufficientQuantityError()
            self.repository.add_trade(
                session,
                uid=uid,
                account_id=account.id,
                position_id=position.id,
                market=position.market,
                symbol=position.symbol,
                side="SELL",
                quantity=qty,
                price=px,
                executed_at=when,
                created_at=utc_now(),
                note=note,
            )
            lots = self.repository.list_lots(session, position_ids=[position.id]).get(position.id, [])
            left = current - qty
            position.quantity = left
            position.average_cost = _weighted_average(lots)
            position.updated_at = when
            if left <= 0:
                position.quantity = Decimal("0")
                position.closed_at = when
                position.average_cost = Decimal("0")
            session.flush()
            return self._position_view(session, position)

        return self._mutate("sell", uid, operation_id, {
            "position_id": position_id, "quantity": str(qty.normalize()), "price": str(px.normalize()), "note": note,
            "executed_at": _when(executed_at) if executed_at is not None else None,
        }, write)

    def update_position(
        self,
        uid: int,
        position_id: int,
        *,
        trade_engine_enabled: bool | None = None,
    ) -> dict[str, Any]:
        def write(session: Session):
            position = self.repository.lock_position(session, uid=uid, position_id=position_id)
            if position is None:
                raise PortfolioError("持仓不存在")
            if trade_engine_enabled is not None:
                position.trade_engine_enabled = bool(trade_engine_enabled)
            position.updated_at = utc_now()
            session.flush()
            return self._position_view(session, position)

        return self.repository.run_write("portfolio.update_position", write)

    def get_position(self, uid: int, position_id: int) -> dict[str, Any] | None:
        with self.repository.db.get_session() as session:
            position = self.repository.get_position(session, uid=uid, position_id=position_id)
            if position is None:
                return None
            return self._position_view(session, position)

    def list_positions(self, uid: int, *, market: str | None = None) -> list[dict[str, Any]]:
        self.ensure_accounts(uid)
        with self.repository.db.get_session() as session:
            rows = self.repository.list_open_positions(session, uid=uid, market=market)
            return [self._position_view(session, row) for row in rows]

    def list_operations(self, uid: int, position_id: int) -> list[dict[str, Any]]:
        with self.repository.db.get_session() as session:
            position = self.repository.get_position(session, uid=uid, position_id=position_id)
            if position is None:
                raise PortfolioError("持仓不存在")
            return [self._operation_view(row) for row in self.repository.list_operations(session, uid=uid, position_id=position_id)]

    def _account_view(self, account) -> dict[str, Any]:
        market = account.market
        return {
            "id": account.id,
            "uid": account.uid,
            "name": account.name,
            "market": market,
            "cash": _dec(account.cash),
            "currency": "CNY" if market == "CN" else "USD",
            "created_at": account.created_at,
            "updated_at": account.updated_at,
        }

    def _position_view(self, session: Session, position: PortfolioPosition) -> dict[str, Any]:
        lots = self.repository.list_lots(session, position_ids=[position.id]).get(position.id, [])
        return {
            "id": position.id,
            "uid": position.uid,
            "account_id": position.account_id,
            "market": position.market,
            "symbol": position.symbol,
            "asset_type": position.asset_type,
            "quantity": _dec(position.quantity),
            "average_cost": _dec(position.average_cost),
            "trade_engine_enabled": True
            if getattr(position, "trade_engine_enabled", None) is None
            else bool(position.trade_engine_enabled),
            "opened_at": position.opened_at,
            "closed_at": position.closed_at,
            "updated_at": position.updated_at,
            "lots": [
                {
                    "id": lot.id,
                    "role": lot.role,
                    "entry_price": _dec(lot.entry_price),
                    "entry_time": lot.entry_time,
                    "original_quantity": _dec(lot.original_quantity),
                    "remaining_quantity": _dec(lot.remaining_quantity),
                    "closed_at": lot.closed_at,
                }
                for lot in lots
            ],
        }

    def _operation_view(self, row) -> dict[str, Any]:
        return {
            "id": row.id,
            "uid": row.uid,
            "account_id": row.account_id,
            "position_id": row.position_id,
            "market": row.market,
            "symbol": row.symbol,
            "side": row.side,
            "quantity": _dec(row.quantity),
            "price": _dec(row.price),
            "executed_at": row.executed_at,
            "created_at": row.created_at,
            "note": row.note,
        }


__all__ = ["PortfolioService"]
