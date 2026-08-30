from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from finance_analysis.core.paths import PROJECT_ROOT


def _load_migration() -> ModuleType:
    path = Path(PROJECT_ROOT) / "alembic" / "versions" / "0025_portfolio_accounts.py"
    spec = importlib.util.spec_from_file_location("portfolio_accounts_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_dependencies(connection) -> None:
    connection.execute(
        text(
            "CREATE TABLE users ("
            "id INTEGER PRIMARY KEY, username VARCHAR(64), email VARCHAR(255), "
            "password_hash TEXT, avatar_url VARCHAR(512), role VARCHAR(32), extra JSON, "
            "created_at DATETIME, updated_at DATETIME)"
        )
    )
    connection.execute(text("CREATE TABLE stock_daily (id INTEGER PRIMARY KEY)"))
    connection.execute(text("CREATE TABLE stock_minute (id INTEGER PRIMARY KEY)"))
    connection.execute(
        text(
            "CREATE TABLE market_data_symbol ("
            "id INTEGER PRIMARY KEY, market VARCHAR(8), code VARCHAR(32), name VARCHAR(255), "
            "enabled BOOLEAN, sync_daily BOOLEAN, sync_minute BOOLEAN, lot_size INTEGER, "
            "created_at DATETIME, updated_at DATETIME)"
        )
    )


def test_portfolio_migration_creates_accounts_discards_legacy_holdings_and_downgrades() -> None:
    migration = _load_migration()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        _create_dependencies(connection)
        connection.execute(text("INSERT INTO users (id) VALUES (1), (2)"))
        connection.execute(text("CREATE TABLE stock_list (id INTEGER PRIMARY KEY, code VARCHAR(16))"))
        connection.execute(text("INSERT INTO stock_list VALUES (1, 'AAPL')"))
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()

        tables = set(inspect(connection).get_table_names())
        assert {
            "portfolio_account",
            "account_cash_balance",
            "instrument",
            "option_contract",
            "position",
        }.issubset(tables)
        assert "stock_list" not in tables
        accounts = connection.execute(
            text("SELECT uid, account_code, market, currency FROM portfolio_account " "ORDER BY uid, id")
        ).all()
        assert accounts == [
            (1, "CN", "CN", "CNY"),
            (1, "HK", "HK", "HKD"),
            (1, "US", "US", "USD"),
            (2, "CN", "CN", "CNY"),
            (2, "HK", "HK", "HKD"),
            (2, "US", "US", "USD"),
        ]
        assert connection.execute(text("SELECT COUNT(*) FROM account_cash_balance")).scalar_one() == 6
        assert connection.execute(text("SELECT COUNT(*) FROM account_cash_balance WHERE balance = 0")).scalar_one() == 6

        migration.upgrade()
        assert connection.execute(text("SELECT COUNT(*) FROM portfolio_account")).scalar_one() == 6

        migration.downgrade()
        downgraded = set(inspect(connection).get_table_names())
        assert "portfolio_account" not in downgraded
        assert "position" not in downgraded
        assert "stock_list" in downgraded
        assert connection.execute(text("SELECT COUNT(*) FROM stock_list")).scalar_one() == 0


def _upgrade_with_repository_alembic(engine) -> None:
    config = Config(str(Path(PROJECT_ROOT) / "alembic.ini"))
    config.attributes["connection"] = engine
    command.upgrade(config, "head")


def test_empty_database_upgrade_creates_current_schema_and_stamps_head() -> None:
    engine = create_engine("sqlite://")
    _upgrade_with_repository_alembic(engine)

    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0033_trend_pending_action"
        assert {
            "portfolio_account",
            "account_cash_balance",
            "instrument",
            "option_contract",
            "position",
            "trend_following_snapshot",
            "trend_following_summary",
        }.issubset(tables)
        assert "stock_list" not in tables


def test_upgrade_from_previous_head_seeds_users_and_discards_legacy_rows() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0024_quant_market_dependencies')"))
        _create_dependencies(connection)
        connection.execute(text("INSERT INTO users (id) VALUES (1), (2)"))
        connection.execute(text("CREATE TABLE stock_list (id INTEGER PRIMARY KEY, code VARCHAR(16))"))
        connection.execute(text("INSERT INTO stock_list VALUES (1, 'AAPL.US')"))

    _upgrade_with_repository_alembic(engine)

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0033_trend_pending_action"
        assert connection.scalar(text("SELECT COUNT(*) FROM portfolio_account")) == 6
        assert connection.scalar(text("SELECT COUNT(*) FROM account_cash_balance")) == 6
        assert "stock_list" not in inspect(connection).get_table_names()
        assert {"trend_following_snapshot", "trend_following_summary"}.issubset(
            inspect(connection).get_table_names()
        )
