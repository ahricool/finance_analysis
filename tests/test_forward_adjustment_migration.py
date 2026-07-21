from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from finance_analysis.core.paths import PROJECT_ROOT


def _load_migration() -> ModuleType:
    path = Path(PROJECT_ROOT) / "alembic" / "versions" / "0022_forward_adjustment_naming.py"
    spec = importlib.util.spec_from_file_location("forward_adjustment_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _SQLiteOperations:
    """Run data-changing migration operations; SQLite cannot rename named checks."""

    def __init__(self, connection):
        self.connection = connection
        self.operations = Operations(MigrationContext.configure(connection))

    def get_bind(self):
        return self.connection

    def alter_column(self, table_name, column_name, **kwargs):
        new_name = kwargs.get("new_column_name")
        if new_name:
            self.connection.execute(
                text(f'ALTER TABLE "{table_name}" RENAME COLUMN "{column_name}" TO "{new_name}"')
            )
        # The production migration also widens PostgreSQL VARCHAR. SQLite has no meaningful equivalent.

    def execute(self, statement):
        return self.connection.execute(text(statement) if isinstance(statement, str) else statement)

    def drop_constraint(self, *args, **kwargs):
        return None

    def create_check_constraint(self, *args, **kwargs):
        return None


def test_forward_adjustment_migration_renames_without_data_loss_and_round_trips() -> None:
    migration = _load_migration()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE stock_adjustment_factor ("
                "id INTEGER PRIMARY KEY, symbol_id INTEGER NOT NULL, trade_date DATE NOT NULL, "
                "qfq_factor FLOAT, UNIQUE(symbol_id, trade_date))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE quant_dataset_snapshot ("
                "id INTEGER PRIMARY KEY, price_mode VARCHAR(16) NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO stock_adjustment_factor "
                "(id, symbol_id, trade_date, qfq_factor) VALUES (1, 9, '2026-07-17', 0.5)"
            )
        )
        connection.execute(text("INSERT INTO quant_dataset_snapshot VALUES (1, 'adjusted')"))
        migration.op = _SQLiteOperations(connection)

        migration.upgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("stock_adjustment_factor")}
        assert "forward_adjustment_factor" in columns
        assert "qfq_factor" not in columns
        assert connection.execute(
            text("SELECT forward_adjustment_factor FROM stock_adjustment_factor WHERE id = 1")
        ).scalar_one() == 0.5
        assert connection.execute(text("SELECT price_mode FROM quant_dataset_snapshot")).scalar_one() == (
            "forward_adjusted"
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO stock_adjustment_factor "
                    "(id, symbol_id, trade_date, forward_adjustment_factor) "
                    "VALUES (2, 9, '2026-07-17', 0.8)"
                )
            )

        migration.downgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("stock_adjustment_factor")}
        assert "qfq_factor" in columns
        assert (
            connection.execute(
                text("SELECT qfq_factor FROM stock_adjustment_factor WHERE id = 1")
            ).scalar_one()
            == 0.5
        )
        assert connection.execute(text("SELECT price_mode FROM quant_dataset_snapshot")).scalar_one() == "adjusted"
