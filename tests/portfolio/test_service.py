"""DB portfolio buy/sell/cash and CORE/ADDON lot attribution."""

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from finance_analysis.database.models.portfolio import (  # pragma: allowlist secret
    CashOperation,
    PortfolioAccount,
    PortfolioPosition,
    PositionLot,
    TradeOperation,
)
from finance_analysis.database.repositories.portfolio import PortfolioRepository  # pragma: allowlist secret
from finance_analysis.portfolio.errors import InsufficientCashError  # pragma: allowlist secret
from finance_analysis.portfolio.service import PortfolioService  # pragma: allowlist secret


class Database:
    def __init__(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        for model in (PortfolioAccount, PortfolioPosition, PositionLot, TradeOperation, CashOperation):
            model.__table__.create(self.engine)

    @contextmanager
    def get_session(self):
        with Session(self.engine) as session:
            yield session

    def _run_write_transaction(self, name, write):
        with Session(self.engine) as session:
            try:
                result = write(session)
                session.commit()
                return result
            except Exception:
                session.rollback()
                raise


def _service():
    return PortfolioService(PortfolioRepository(Database()))


def test_deposit_buy_addon_sell_updates_cash_lots_and_average_cost():
    service = _service()
    accounts = service.ensure_accounts(1)
    cn = next(item for item in accounts if item["market"] == "CN")
    when = datetime(2026, 9, 1, 9, 30, tzinfo=timezone.utc)
    service.deposit(1, account_id=cn["id"], amount="100000", executed_at=when)
    first = service.buy(1, account_id=cn["id"], symbol="600519.SH", quantity="1000", price="10", executed_at=when)
    assert first["quantity"] == Decimal("1000")
    assert first["average_cost"] == Decimal("10")
    roles = {lot["role"]: lot["remaining_quantity"] for lot in first["lots"]}
    assert roles == {"CORE": Decimal("1000")}
    cash = next(item for item in service.list_accounts(1, market="CN") if item["id"] == cn["id"])["cash"]
    assert cash == Decimal("90000")

    second = service.buy(
        1,
        account_id=cn["id"],
        symbol="600519.SH",
        quantity="500",
        price="12",
        executed_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
    )
    assert second["id"] == first["id"]
    assert second["quantity"] == Decimal("1500")
    roles = {lot["role"]: lot["remaining_quantity"] for lot in second["lots"]}
    assert roles["CORE"] == Decimal("1000")
    assert roles["ADDON"] == Decimal("500")

    sold = service.sell(
        1,
        position_id=second["id"],
        quantity="300",
        price="13",
        executed_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )
    assert sold["quantity"] == Decimal("1200")
    roles = {lot["role"]: lot["remaining_quantity"] for lot in sold["lots"] if lot["remaining_quantity"] > 0}
    assert roles["CORE"] == Decimal("1000")
    assert roles["ADDON"] == Decimal("200")
    assert sold["average_cost"] == Decimal("12400") / Decimal("1200")
    cash = next(item for item in service.list_accounts(1, market="CN") if item["id"] == cn["id"])["cash"]
    assert cash == Decimal("87900")


def test_full_sell_closes_position_and_next_buy_starts_new_core():
    service = _service()
    cn = next(item for item in service.ensure_accounts(7) if item["market"] == "CN")
    service.deposit(7, account_id=cn["id"], amount="100000")
    opened = service.buy(7, account_id=cn["id"], symbol="600519.SH", quantity="100", price="10")
    closed = service.sell(7, position_id=opened["id"], quantity="100", price="11")
    assert closed["quantity"] == Decimal("0")
    assert closed["closed_at"] is not None
    again = service.buy(7, account_id=cn["id"], symbol="600519.SH", quantity="50", price="12")
    assert again["id"] != opened["id"]
    assert [lot["role"] for lot in again["lots"]] == ["CORE"]


def test_buy_rejects_insufficient_cash():
    service = _service()
    cn = next(item for item in service.ensure_accounts(3) if item["market"] == "CN")
    try:
        service.buy(3, account_id=cn["id"], symbol="600519.SH", quantity="1", price="10")
    except InsufficientCashError:
        return
    raise AssertionError("expected insufficient cash")
