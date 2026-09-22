"""DB portfolio buy/sell/cash and CORE/ADDON lot attribution."""

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal

import pytest

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
from finance_analysis.database.models.stock import Instrument  # pragma: allowlist secret
from finance_analysis.portfolio.errors import PortfolioError  # pragma: allowlist secret
from finance_analysis.portfolio.service import PortfolioService  # pragma: allowlist secret


class Database:
    def __init__(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        for model in (Instrument, PortfolioAccount, PortfolioPosition, PositionLot, TradeOperation, CashOperation):
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
    db = Database()
    with db.get_session() as session:
        for code, market, kind in [("600519.SH", "CN", "STOCK"), ("510300.SH", "CN", "ETF"),
                                   ("AAPL.US", "US", "STOCK"), ("000001.SH", "CN", "INDEX")]:
            session.add(Instrument(code=code, market=market, native_code=code.split(".")[0],
                                   name=code, instrument_type=kind, currency="CNY" if market == "CN" else "USD",
                                   source="MANUAL"))
        session.commit()
    return PortfolioService(PortfolioRepository(db))


def test_buy_addon_sell_preserves_cash_and_updates_lots_and_average_cost():
    service = _service()
    accounts = service.ensure_accounts(1)
    cn = next(item for item in accounts if item["market"] == "CN")
    when = datetime(2026, 9, 1, 9, 30, tzinfo=timezone.utc)
    service.set_cash(1, account_id=cn["id"], amount="100000")
    first = service.buy(1, account_id=cn["id"], symbol="600519.SH", quantity="1000", price="10", executed_at=when)
    assert first["quantity"] == Decimal("1000")
    assert first["average_cost"] == Decimal("10")
    assert first["trade_engine_enabled"] is True
    roles = {lot["role"]: lot["remaining_quantity"] for lot in first["lots"]}
    assert roles == {"CORE": Decimal("1000")}
    cash = next(item for item in service.list_accounts(1, market="CN") if item["id"] == cn["id"])["cash"]
    assert cash == Decimal("100000")

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
    assert cash == Decimal("100000")


def test_full_sell_closes_position_and_next_buy_starts_new_core():
    service = _service()
    cn = next(item for item in service.ensure_accounts(7) if item["market"] == "CN")
    service.set_cash(7, account_id=cn["id"], amount="100000")
    opened = service.buy(7, account_id=cn["id"], symbol="600519.SH", quantity="100", price="10")
    closed = service.sell(7, position_id=opened["id"], quantity="100", price="11")
    assert closed["quantity"] == Decimal("0")
    assert closed["closed_at"] is not None
    again = service.buy(7, account_id=cn["id"], symbol="600519.SH", quantity="50", price="12")
    assert again["id"] != opened["id"]
    assert [lot["role"] for lot in again["lots"]] == ["CORE"]


def test_buy_and_full_sell_with_zero_cash():
    service = _service()
    cn = next(item for item in service.ensure_accounts(3) if item["market"] == "CN")
    bought = service.buy(3, account_id=cn["id"], symbol="600519.SH", quantity="1", price="10")
    service.sell(3, position_id=bought["id"], quantity="1", price="12")
    assert service.list_accounts(3, market="CN")[0]["cash"] == Decimal("0")


@pytest.mark.parametrize("amount", ["-1", "NaN", "Infinity", "-Infinity", "abc", "1e20"])
def test_set_cash_rejects_invalid_amount(amount):
    service = _service()
    cn = next(item for item in service.ensure_accounts(3) if item["market"] == "CN")
    with pytest.raises(PortfolioError):
        service.set_cash(3, account_id=cn["id"], amount=amount)
    assert service.list_accounts(3, market="CN")[0]["cash"] == 0


def test_set_cash_replaces_balance_and_isolates_user_and_market():
    service = _service()
    cn = next(item for item in service.ensure_accounts(3) if item["market"] == "CN")
    service.set_cash(3, account_id=cn["id"], amount="100.25")
    service.set_cash(3, account_id=cn["id"], amount="50.125")
    assert service.list_accounts(3, market="CN")[0]["cash"] == Decimal("50.125")
    assert service.list_accounts(3, market="US")[0]["cash"] == 0
    with pytest.raises(PortfolioError, match="账户不存在"):
        service.set_cash(4, account_id=cn["id"], amount="0")
    assert service.list_accounts(3, market="CN")[0]["cash"] == Decimal("50.125")
    assert service.set_cash(3, account_id=cn["id"], amount="0")["cash"] == 0


@pytest.mark.parametrize("symbol", ["999999.SH", "000001.SH", "AAPL.US"])
def test_buy_rejects_missing_instrument_index_and_wrong_market(symbol):
    service = _service()
    cn = next(item for item in service.ensure_accounts(3) if item["market"] == "CN")
    with pytest.raises(PortfolioError):
        service.buy(3, account_id=cn["id"], symbol=symbol, quantity="1", price="10")
    assert service.list_positions(3) == []


def test_buy_uses_instrument_asset_type():
    service = _service()
    cn = next(item for item in service.ensure_accounts(3) if item["market"] == "CN")
    result = service.buy(3, account_id=cn["id"], symbol="510300.SH", quantity="100", price="4")
    assert result["asset_type"] == "ETF"


def test_update_position_toggles_trade_engine_without_changing_lots():
    service = _service()
    cn = next(item for item in service.ensure_accounts(9) if item["market"] == "CN")
    service.set_cash(9, account_id=cn["id"], amount="100000")
    opened = service.buy(9, account_id=cn["id"], symbol="600519.SH", quantity="100", price="10")
    assert opened["trade_engine_enabled"] is True
    updated = service.update_position(9, opened["id"], trade_engine_enabled=False)
    assert updated["trade_engine_enabled"] is False
    assert updated["quantity"] == Decimal("100")
    assert updated["id"] == opened["id"]
    again = service.update_position(9, opened["id"], trade_engine_enabled=True)
    assert again["trade_engine_enabled"] is True
    assert "strategy_key" not in again
