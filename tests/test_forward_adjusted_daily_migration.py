from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect, text

from finance_analysis.core.paths import PROJECT_ROOT


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


def test_migration_converts_existing_ohlc_once_and_removes_legacy_indirection() -> None:
    migration = _load_migration()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE market_data_symbol (id INTEGER PRIMARY KEY)"))
        connection.execute(
            text(
                "CREATE TABLE stock_daily (id INTEGER PRIMARY KEY, symbol_id INTEGER NOT NULL, date DATE NOT NULL, "
                "open FLOAT, high FLOAT, low FLOAT, close FLOAT, vwap FLOAT, limit_up FLOAT, limit_down FLOAT)"
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
        connection.execute(
            text("INSERT INTO stock_daily VALUES (1, 9, '2026-07-17', 100, 102, 98, 100, 99, 110, 90)")
        )
        connection.execute(
            text("INSERT INTO stock_daily VALUES (2, 10, '2026-07-17', 20, 21, 19, 20, NULL, NULL, NULL)")
        )
        connection.execute(text("INSERT INTO stock_adjustment_factor VALUES (1, 9, '2026-07-17', 0.5)"))
        connection.execute(text("INSERT INTO quant_dataset_snapshot VALUES (1, 'forward_adjusted', 'ready')"))
        connection.execute(text("INSERT INTO backtest_run VALUES (1, 'raw', 'completed')"))
        migration.op = _SQLiteOperations(connection)

        migration.upgrade()

        assert connection.execute(
            text("SELECT open, high, low, close, vwap, limit_up, limit_down FROM stock_daily WHERE id = 1")
        ).one() == (50.0, 51.0, 49.0, 50.0, 49.5, 55.0, 45.0)
        assert connection.execute(text("SELECT count(*) FROM stock_daily")).scalar_one() == 1
        assert "stock_adjustment_factor" not in inspect(connection).get_table_names()
        assert "price_mode" not in {item["name"] for item in inspect(connection).get_columns("quant_dataset_snapshot")}
        assert "price_mode" not in {item["name"] for item in inspect(connection).get_columns("backtest_run")}

        with pytest.raises(RuntimeError, match="irreversible"):
            migration.downgrade()
