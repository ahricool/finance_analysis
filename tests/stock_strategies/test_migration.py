import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, inspect
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from finance_analysis.database.models.stock_strategies import (
    StockStrategyDay,
    StockStrategyLaunch,
    StockStrategyRun,
    StockStrategyState,
)


def test_migration_single_head_matches_models_and_reverses():
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    assert ScriptDirectory.from_config(cfg).get_current_head() == "0080_signal_center_v2"
    spec = importlib.util.spec_from_file_location("stock_migration", root / "alembic/versions/0076_stock_strategies.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with create_engine("sqlite://").begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        for model in (StockStrategyLaunch, StockStrategyState, StockStrategyDay, StockStrategyRun):
            table = model.__table__
            columns = {c["name"]: c for c in inspect(connection).get_columns(table.name)}
            assert set(columns) == set(table.columns.keys())
            assert inspect(connection).get_pk_constraint(table.name)["constrained_columns"] == [
                c.name for c in table.primary_key
            ]
            for c in table.columns:
                assert columns[c.name]["nullable"] == c.nullable
            assert {c["name"] for c in inspect(connection).get_check_constraints(table.name)} == {
                c.name for c in table.constraints if c.__class__.__name__ == "CheckConstraint"
            }
        module.downgrade()
        assert inspect(connection).get_table_names() == []
