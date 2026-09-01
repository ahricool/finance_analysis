from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect, text

from finance_analysis.core.paths import PROJECT_ROOT
from finance_analysis.database.models.stock import MarketDataSymbol


def _load_migration() -> ModuleType:
    path = Path(PROJECT_ROOT) / "alembic" / "versions" / "0037_forward_adjusted_daily_storage.py"
    spec = importlib.util.spec_from_file_location("forward_adjusted_daily_storage", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _SQLiteOperations:
    def __init__(self, connection):
        self.connection = connection
        self.operations = Operations(MigrationContext.configure(connection))

    def get_bind(self):
        return self.connection

    def execute(self, statement):
        return self.connection.execute(text(statement) if isinstance(statement, str) else statement)

    def drop_table(self, table_name):
        self.operations.drop_table(table_name)

    def drop_column(self, table_name, column_name):
        self.operations.drop_column(table_name, column_name)

    def drop_constraint(self, *args, **kwargs):
        return None


def test_migration_converts_ohlc_and_removes_legacy_daily_and_backtest_schema() -> None:
    migration = _load_migration()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE market_data_symbol (id INTEGER PRIMARY KEY, lot_size INTEGER)"))
        connection.execute(
            text(
                "CREATE TABLE stock_daily (id INTEGER PRIMARY KEY, symbol_id INTEGER NOT NULL, date DATE NOT NULL, "
                "open FLOAT, high FLOAT, low FLOAT, close FLOAT, volume FLOAT, amount FLOAT, "
                "data_source VARCHAR(32), created_at DATETIME, updated_at DATETIME, "
                "vwap FLOAT, vwap_source VARCHAR(32), vwap_quality VARCHAR(16), "
                "limit_up FLOAT, limit_down FLOAT, suspended BOOLEAN)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE stock_adjustment_factor (id INTEGER PRIMARY KEY, symbol_id INTEGER NOT NULL, "
                "trade_date DATE NOT NULL, forward_adjustment_factor FLOAT)"
            )
        )
        connection.execute(
            text("CREATE TABLE quant_dataset_snapshot (id INTEGER PRIMARY KEY, price_mode VARCHAR(24), status VARCHAR(16))")
        )
        connection.execute(
            text("CREATE TABLE backtest_run (id INTEGER PRIMARY KEY, price_mode VARCHAR(16), status VARCHAR(16))")
        )
        connection.execute(text("CREATE TABLE backtest_trade (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL)"))
        connection.execute(text("CREATE TABLE backtest_equity (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL)"))
        connection.execute(
            text(
                "INSERT INTO stock_daily "
                "(id, symbol_id, date, open, high, low, close, volume, amount, data_source, "
                "vwap, vwap_source, vwap_quality, limit_up, limit_down, suspended) "
                "VALUES (1, 9, '2026-07-17', 100, 102, 98, 100, 1000, 100000, 'legacy', "
                "99, 'calculated', 'exact', 110, 90, 0)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO stock_daily "
                "(id, symbol_id, date, open, high, low, close, volume, amount, data_source) "
                "VALUES (2, 10, '2026-07-17', 20, 21, 19, 20, 2000, NULL, 'legacy')"
            )
        )
        connection.execute(text("INSERT INTO stock_adjustment_factor VALUES (1, 9, '2026-07-17', 0.5)"))
        connection.execute(text("INSERT INTO quant_dataset_snapshot VALUES (1, 'forward_adjusted', 'ready')"))
        connection.execute(text("INSERT INTO backtest_run VALUES (1, 'raw', 'completed')"))
        migration.op = _SQLiteOperations(connection)

        migration.upgrade()

        assert connection.execute(
            text("SELECT open, high, low, close, volume, amount, data_source FROM stock_daily WHERE id = 1")
        ).one() == (50.0, 51.0, 49.0, 50.0, 1000.0, 100000.0, "legacy")
        assert connection.execute(text("SELECT count(*) FROM stock_daily")).scalar_one() == 1
        table_names = set(inspect(connection).get_table_names())
        assert "stock_adjustment_factor" not in table_names
        assert {"backtest_run", "backtest_trade", "backtest_equity"}.isdisjoint(table_names)
        assert {column["name"] for column in inspect(connection).get_columns("market_data_symbol")} == {"id"}
        assert {column["name"] for column in inspect(connection).get_columns("stock_daily")} == {
            "id",
            "symbol_id",
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "data_source",
            "created_at",
            "updated_at",
        }
        assert "price_mode" not in {item["name"] for item in inspect(connection).get_columns("quant_dataset_snapshot")}

        with pytest.raises(RuntimeError, match="irreversible"):
            migration.downgrade()


def test_current_symbol_model_has_no_execution_unit_metadata() -> None:
    assert "lot_size" not in MarketDataSymbol.__table__.columns
    constraint_names = {constraint.name for constraint in MarketDataSymbol.__table__.constraints}
    assert "ck_market_data_symbol_lot_size" not in constraint_names
