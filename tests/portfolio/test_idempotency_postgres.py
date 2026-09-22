"""Real receipt migration and concurrent replay in a disposable PostgreSQL schema."""

import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from finance_analysis.database.models.portfolio import PortfolioAccount, PortfolioPosition, PortfolioMutation, PositionLot, TradeOperation
from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.repositories.portfolio import PortfolioRepository
from finance_analysis.portfolio.service import PortfolioService
from finance_analysis.portfolio.errors import OperationConflictError


@pytest.mark.skipif(not os.getenv("PORTFOLIO_TEST_POSTGRES_URL"), reason="Requires disposable PostgreSQL test DB")
def test_migration_and_concurrent_receipts():
    engine = create_engine(os.environ["PORTFOLIO_TEST_POSTGRES_URL"])
    schema = "portfolio_test_" + uuid4().hex
    scoped = engine.execution_options(schema_translate_map={None: schema})
    spec = importlib.util.spec_from_file_location(
        "portfolio_migration", Path(__file__).parents[2] / "alembic/versions/0063_portfolio_mutation.py",
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    class Database:
        @contextmanager
        def get_session(self):
            with Session(scoped) as session:
                yield session

        def _run_write_transaction(self, name, write):
            with Session(scoped) as session, session.begin():
                return write(session)

    db = Database()
    try:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()
            inspector = inspect(conn)
            assert {c["name"] for c in inspector.get_columns("portfolio_mutation", schema=schema)} == set(PortfolioMutation.__table__.columns.keys())
            assert inspector.get_pk_constraint("portfolio_mutation", schema=schema)["constrained_columns"] == ["uid", "operation_id"]
        for model in (Instrument, PortfolioAccount, PortfolioPosition, PositionLot, TradeOperation):
            model.__table__.create(scoped)
        with Session(scoped) as session, session.begin():
            session.add(Instrument(code="600519.SH", market="CN", native_code="600519", name="Test", instrument_type="STOCK", currency="CNY", source="MANUAL"))
        service = PortfolioService(PortfolioRepository(db))
        account = service.ensure_accounts(1)[0]
        key = str(uuid4())
        barrier = Barrier(2)

        def buy(_):
            barrier.wait(timeout=10)
            return service.buy(1, account_id=account["id"], symbol="600519.SH", quantity="10", price="4", operation_id=key)

        with ThreadPoolExecutor(max_workers=2) as pool:
            bought = list(pool.map(buy, range(2)))
        assert bought[0] == bought[1]
        position_id = bought[0]["id"]
        assert service.get_position(1, position_id)["quantity"] == 10
        assert len(service.list_operations(1, position_id)) == 1
        with pytest.raises(OperationConflictError):
            service.buy(1, account_id=account["id"], symbol="600519.SH", quantity="11", price="4", operation_id=key)
        key = str(uuid4())

        def sell(_):
            barrier.wait(timeout=10)
            return service.sell(1, position_id=position_id, quantity="10", price="5", operation_id=key)

        with ThreadPoolExecutor(max_workers=2) as pool:
            sold = list(pool.map(sell, range(2)))
        assert sold[0] == sold[1]
        assert len(service.list_operations(1, position_id)) == 2
        assert service.list_accounts(1, market="CN")[0]["cash"] == 0
        with db.get_session() as session:
            assert len(session.execute(select(PortfolioMutation)).scalars().all()) == 2
        with engine.begin() as conn:
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            migration.op = Operations(MigrationContext.configure(conn))
            migration.downgrade()
            assert not inspect(conn).has_table("portfolio_mutation", schema=schema)
            migration.upgrade()
            assert inspect(conn).has_table("portfolio_mutation", schema=schema)
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
