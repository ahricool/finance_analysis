from __future__ import annotations

import importlib.util
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from finance_analysis.core.paths import PROJECT_ROOT
from finance_analysis.database.repositories.user import UserRepository
from finance_analysis.interfaces.api.v1.endpoints import portfolio
from finance_analysis.interfaces.api.v1.router import router as v1_router
from finance_analysis.interfaces.api.v1.schemas.portfolio import (
    CashBalanceUpdate,
    EquityPositionCreate,
    OptionPositionCreate,
)
from finance_analysis.portfolio.domain import (
    build_option_canonical_symbol,
    current_us_market_date,
    normalize_portfolio_canonical_symbol,
    option_days_to_expiration,
)
from finance_analysis.portfolio.service import (
    PortfolioConflictError,
    PortfolioService,
    PortfolioValidationError,
)


NOW = datetime(2026, 7, 29, 2, 30, tzinfo=timezone.utc)


class TestDatabase:
    __test__ = False

    def __init__(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._build_schema()

    def _build_schema(self):
        path = Path(PROJECT_ROOT) / "alembic" / "versions" / "0025_portfolio_accounts.py"
        spec = importlib.util.spec_from_file_location("portfolio_test_migration", path)
        assert spec is not None and spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64), "
                    "email VARCHAR(255), password_hash TEXT, avatar_url VARCHAR(512), role VARCHAR(32), "
                    "extra JSON, created_at DATETIME, updated_at DATETIME)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE market_data_symbol (id INTEGER PRIMARY KEY, market VARCHAR(8), "
                    "code VARCHAR(32), name VARCHAR(255), enabled BOOLEAN, sync_daily BOOLEAN, "
                    "created_at DATETIME, updated_at DATETIME)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO users (id, username, email, role, extra, created_at, updated_at) VALUES "
                    "(1, 'one', 'one@example.com', 'user', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                    "(2, 'two', 'two@example.com', 'user', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

    def get_session(self):
        return self.session_factory()

    def _run_write_transaction(self, _operation_name, write_operation):
        session = self.session_factory()
        try:
            result = write_operation(session)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


@pytest.fixture
def portfolio_service():
    return PortfolioService(TestDatabase(), now_provider=lambda: NOW)


def test_option_canonical_symbol_is_stable_across_decimal_spellings() -> None:
    expected = "SPY.US|2026-08-21|CALL|650"
    for strike in ("650", "650.0", "650.00000000", Decimal("650.00")):
        assert build_option_canonical_symbol("spy.us", date(2026, 8, 21), "call", strike) == expected


def test_portfolio_canonical_symbol_normalizes_us_without_changing_cn_or_hk_rules() -> None:
    assert normalize_portfolio_canonical_symbol("US", "AAPL") == "AAPL.US"
    assert normalize_portfolio_canonical_symbol("US", "aapl") == "AAPL.US"
    assert normalize_portfolio_canonical_symbol("US", "AAPL.US") == "AAPL.US"
    assert normalize_portfolio_canonical_symbol("CN", "600519.sh") == "600519.SH"
    assert normalize_portfolio_canonical_symbol("HK", "700.hk") == "700.HK"
    assert build_option_canonical_symbol("SPY", date(2026, 8, 21), "CALL", "650") == (
        "SPY.US|2026-08-21|CALL|650"
    )


def test_us_equities_and_option_underlying_are_normalized_before_storage(portfolio_service) -> None:
    portfolio_service.ensure_fixed_portfolio_accounts(1)
    portfolio_service.ensure_fixed_portfolio_accounts(2)
    first_us = portfolio_service.accounts.get_by_code(1, "US")
    second_us = portfolio_service.accounts.get_by_code(2, "US")

    first = portfolio_service.create_equity_position(
        1,
        first_us.id,
        canonical_symbol="AAPL",
        display_symbol="AAPL",
        name="Apple",
        asset_type="STOCK",
        quantity="1",
        avg_cost="100",
        opened_at=None,
        notes=None,
    )
    second = portfolio_service.create_equity_position(
        2,
        second_us.id,
        canonical_symbol="aapl",
        display_symbol="AAPL",
        name="Apple",
        asset_type="STOCK",
        quantity="2",
        avg_cost="101",
        opened_at=None,
        notes=None,
    )
    assert first.instrument.canonical_symbol == "AAPL.US"
    assert second.instrument.canonical_symbol == "AAPL.US"

    option = portfolio_service.create_option_position(
        1,
        first_us.id,
        underlying_canonical_symbol="SPY",
        underlying_display_symbol="SPY",
        underlying_name="SPDR S&P 500 ETF Trust",
        underlying_asset_type="ETF",
        option_type="CALL",
        expiration_date=date(2026, 8, 21),
        strike_price="650",
        quantity="1",
        avg_cost="3.50",
        contract_multiplier="100",
        opened_at=None,
        notes=None,
    )
    option_payload = portfolio_service.position_payload(option)
    assert option_payload["canonical_symbol"] == "SPY.US|2026-08-21|CALL|650"
    assert option_payload["option"]["underlying_canonical_symbol"] == "SPY.US"


def test_option_dte_uses_new_york_date_boundary() -> None:
    before_midnight_ny = datetime(2026, 7, 29, 3, 30, tzinfo=timezone.utc)
    after_midnight_ny = datetime(2026, 7, 29, 4, 30, tzinfo=timezone.utc)
    assert current_us_market_date(before_midnight_ny) == date(2026, 7, 28)
    assert current_us_market_date(after_midnight_ny) == date(2026, 7, 29)
    assert option_days_to_expiration(date(2026, 7, 29), before_midnight_ny) == 1
    assert option_days_to_expiration(date(2026, 7, 29), after_midnight_ny) == 0


@pytest.mark.parametrize(
    ("expiration_date", "expected"),
    (
        (date(2026, 8, 8), 11),
        (date(2026, 8, 4), 7),
        (date(2026, 7, 29), 1),
        (date(2026, 7, 28), 0),
        (date(2026, 7, 27), -1),
    ),
)
def test_option_dte_natural_day_boundaries(expiration_date, expected) -> None:
    now = datetime(2026, 7, 29, 3, 30, tzinfo=timezone.utc)
    assert option_days_to_expiration(expiration_date, now) == expected


def test_fixed_accounts_are_ordered_idempotent_and_isolated(portfolio_service) -> None:
    first = portfolio_service.ensure_fixed_portfolio_accounts(1)
    second = portfolio_service.ensure_fixed_portfolio_accounts(1)
    other = portfolio_service.ensure_fixed_portfolio_accounts(2)
    assert [(row.account_code, row.currency) for row in first] == [
        ("CN", "CNY"),
        ("HK", "HKD"),
        ("US", "USD"),
    ]
    assert [row.id for row in second] == [row.id for row in first]
    assert {row.id for row in first}.isdisjoint({row.id for row in other})
    assert all(row.cash_balance.balance == Decimal("0E-8") for row in first)
    assert portfolio_service.accounts.get_by_id(other[0].id, 1) is None


def test_new_user_and_default_admin_receive_fixed_accounts() -> None:
    database = TestDatabase()
    users = UserRepository(database)
    created = users.create_user(email="new@example.com", username="new")
    admin_uid = users.ensure_default_admin()
    accounts = PortfolioService(database).accounts
    assert [item.account_code for item in accounts.list_by_uid(created.id)] == ["CN", "HK", "US"]
    assert [item.account_code for item in accounts.list_by_uid(admin_uid)] == ["CN", "HK", "US"]


def test_cash_supports_negative_and_full_decimal_precision(portfolio_service) -> None:
    cn = portfolio_service.accounts.get_by_code(1, "CN")
    updated = portfolio_service.set_cash_balance(1, cn.id, "-123.12345678")
    assert updated.cash_balance.balance == Decimal("-123.12345678")


def test_equity_and_option_positions_enforce_market_quantity_and_cost(portfolio_service) -> None:
    cn = portfolio_service.accounts.get_by_code(1, "CN")
    us = portfolio_service.accounts.get_by_code(1, "US")
    stock = portfolio_service.create_equity_position(
        1,
        cn.id,
        canonical_symbol="600519.SH",
        display_symbol="600519",
        name="贵州茅台",
        asset_type="STOCK",
        quantity="10.5",
        avg_cost="650.25",
        opened_at=None,
        notes=None,
    )
    assert portfolio_service.position_payload(stock)["cost_amount"] == "6827.62500000"
    with pytest.raises(PortfolioValidationError):
        portfolio_service.create_equity_position(
            1,
            cn.id,
            canonical_symbol="AAPL.US",
            display_symbol="AAPL",
            name="Apple",
            asset_type="STOCK",
            quantity="1",
            avg_cost="1",
            opened_at=None,
            notes=None,
        )
    with pytest.raises(PortfolioValidationError, match="must not be 0"):
        portfolio_service.create_equity_position(
            1,
            us.id,
            canonical_symbol="AAPL.US",
            display_symbol="AAPL",
            name="Apple",
            asset_type="STOCK",
            quantity="0",
            avg_cost="1",
            opened_at=None,
            notes=None,
        )

    option = portfolio_service.create_option_position(
        1,
        us.id,
        underlying_canonical_symbol="SPY",
        underlying_display_symbol="SPY",
        underlying_name="SPDR S&P 500 ETF Trust",
        underlying_asset_type="ETF",
        option_type="PUT",
        expiration_date=date(2026, 8, 21),
        strike_price="650.0",
        quantity="-2",
        avg_cost="3.50",
        contract_multiplier="100",
        opened_at=NOW,
        notes="manual",
    )
    payload = portfolio_service.position_payload(option)
    assert payload["position_side"] == "SHORT"
    assert payload["cost_amount"] == "700.00000000"
    assert payload["option"]["underlying_canonical_symbol"] == "SPY.US"
    assert payload["option"]["days_to_expiration"] == 24
    assert option.instrument.market_data_symbol_id is None
    with pytest.raises(PortfolioValidationError, match="must equal 100"):
        portfolio_service.create_option_position(
            1,
            us.id,
            underlying_canonical_symbol="QQQ",
            underlying_display_symbol="QQQ",
            underlying_name="Invesco QQQ Trust",
            underlying_asset_type="ETF",
            option_type="CALL",
            expiration_date=date(2026, 9, 18),
            strike_price="700",
            quantity="1",
            avg_cost="2",
            contract_multiplier="50",
            opened_at=None,
            notes=None,
        )
    with pytest.raises(PortfolioValidationError, match="integer"):
        portfolio_service.create_option_position(
            1,
            us.id,
            underlying_canonical_symbol="AAPL.US",
            underlying_display_symbol="AAPL",
            underlying_name="Apple",
            underlying_asset_type="STOCK",
            option_type="CALL",
            expiration_date=date(2026, 9, 18),
            strike_price="200",
            quantity="1.5",
            avg_cost="2",
            opened_at=None,
            notes=None,
        )


def test_position_repository_filters_open_equities_by_owner_and_market(portfolio_service) -> None:
    cn = portfolio_service.accounts.get_by_code(1, "CN")
    us = portfolio_service.accounts.get_by_code(1, "US")
    cn_etf = portfolio_service.create_equity_position(
        1,
        cn.id,
        canonical_symbol="510300.SH",
        display_symbol="510300",
        name="沪深300ETF",
        asset_type="ETF",
        quantity="12.5",
        avg_cost="4.12345678",
        opened_at=None,
        notes=None,
    )
    us_stock = portfolio_service.create_equity_position(
        1,
        us.id,
        canonical_symbol="AAPL.US",
        display_symbol="AAPL",
        name="Apple",
        asset_type="STOCK",
        quantity="2",
        avg_cost="200",
        opened_at=None,
        notes=None,
    )
    portfolio_service.create_option_position(
        1,
        us.id,
        underlying_canonical_symbol="SPY.US",
        underlying_display_symbol="SPY",
        underlying_name="SPDR S&P 500 ETF Trust",
        underlying_asset_type="ETF",
        option_type="CALL",
        expiration_date=date(2026, 8, 21),
        strike_price="650",
        quantity="1",
        avg_cost="3.5",
        opened_at=None,
        notes=None,
    )
    portfolio_service.update_position(1, us_stock.id, status="CLOSED")

    cn_positions = portfolio_service.positions.list_open_by_uid_and_market(
        1, "CN", ("STOCK", "ETF")
    )
    us_positions = portfolio_service.positions.list_open_by_uid_and_market(
        1, "US", ("STOCK", "ETF")
    )
    other_user_positions = portfolio_service.positions.list_open_by_uid_and_market(
        2, "CN", ("STOCK", "ETF")
    )
    assert [position.id for position in cn_positions] == [cn_etf.id]
    assert us_positions == []
    assert other_user_positions == []


def test_duplicate_position_is_rejected(portfolio_service) -> None:
    us = portfolio_service.accounts.get_by_code(1, "US")
    payload = {
        "canonical_symbol": "AAPL.US",
        "display_symbol": "AAPL",
        "name": "Apple",
        "asset_type": "STOCK",
        "quantity": "1",
        "avg_cost": "100",
        "opened_at": None,
        "notes": None,
    }
    portfolio_service.create_equity_position(1, us.id, **payload)
    with pytest.raises(PortfolioConflictError):
        portfolio_service.create_equity_position(1, us.id, **payload)


def test_expired_option_requires_explicit_valid_status_update(portfolio_service) -> None:
    us = portfolio_service.accounts.get_by_code(1, "US")
    option = portfolio_service.create_option_position(
        1,
        us.id,
        underlying_canonical_symbol="AAPL.US",
        underlying_display_symbol="AAPL",
        underlying_name="Apple",
        underlying_asset_type="STOCK",
        option_type="CALL",
        expiration_date=date(2026, 7, 28),
        strike_price="200",
        quantity="1",
        avg_cost="2",
        opened_at=None,
        notes=None,
    )
    portfolio_service.now_provider = lambda: datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
    open_payload = portfolio_service.position_payload(option)
    assert open_payload["option"]["days_to_expiration"] < 0
    assert open_payload["option"]["expiration_action_required"] is True
    expired = portfolio_service.update_position(1, option.id, status="EXPIRED")
    assert expired.status == "EXPIRED"
    assert expired.closed_at is not None
    assert portfolio_service.position_payload(expired)["option"]["expiration_action_required"] is False


def test_decimal_request_fields_reject_json_numbers() -> None:
    with pytest.raises(ValidationError):
        CashBalanceUpdate(balance=1.2)
    with pytest.raises(ValidationError):
        EquityPositionCreate(
            canonical_symbol="AAPL.US",
            display_symbol="AAPL",
            asset_type="STOCK",
            quantity=1,
            avg_cost="2",
        )
    with pytest.raises(ValidationError):
        OptionPositionCreate(
            underlying_canonical_symbol="SPY.US",
            underlying_display_symbol="SPY",
            underlying_asset_type="ETF",
            option_type="CALL",
            expiration_date=date(2026, 8, 21),
            strike_price="650",
            quantity="2",
            avg_cost="3.5",
            contract_multiplier=100,
        )


def test_portfolio_api_accounts_cash_positions_and_ownership(monkeypatch, portfolio_service) -> None:
    monkeypatch.setattr(portfolio, "_service", lambda: portfolio_service)
    monkeypatch.setattr(portfolio, "get_effective_uid", lambda _request: 1)
    app = FastAPI()
    app.include_router(portfolio.router, prefix="/api/v1/portfolio")
    client = TestClient(app)

    accounts = client.get("/api/v1/portfolio/accounts")
    assert accounts.status_code == 200
    assert [item["account_code"] for item in accounts.json()] == ["CN", "HK", "US"]
    us_id = accounts.json()[2]["id"]
    assert client.put(
        f"/api/v1/portfolio/accounts/{us_id}/cash", json={"balance": "10000.12345678"}
    ).json()["cash_balance"] == "10000.12345678"
    assert client.put(
        f"/api/v1/portfolio/accounts/{us_id}/cash", json={"balance": 10000.12}
    ).status_code == 422
    created = client.post(
        f"/api/v1/portfolio/accounts/{us_id}/positions/equities",
        json={
            "canonical_symbol": "AAPL",
            "display_symbol": "AAPL",
            "name": "Apple",
            "asset_type": "STOCK",
            "quantity": "2",
            "avg_cost": "100",
        },
    )
    assert created.status_code == 201
    assert created.json()["canonical_symbol"] == "AAPL.US"
    assert created.json()["cost_amount"] == "200.00000000"
    listed = client.get(f"/api/v1/portfolio/accounts/{us_id}/positions")
    assert listed.json()[0]["id"] == created.json()["id"]
    assert client.delete(f"/api/v1/portfolio/positions/{created.json()['id']}").status_code == 204

    other_id = portfolio_service.accounts.get_by_code(2, "CN").id
    assert client.get(f"/api/v1/portfolio/accounts/{other_id}").status_code == 404
    assert client.put(
        f"/api/v1/portfolio/accounts/{other_id}/cash", json={"balance": "1"}
    ).status_code == 404


def test_legacy_stock_list_route_is_not_registered() -> None:
    paths = {route.path for route in v1_router.routes}
    assert "/api/v1/stock-list" not in paths
    assert "/api/v1/portfolio/accounts" in paths
