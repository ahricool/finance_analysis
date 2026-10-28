import importlib.util
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql
from finance_analysis.database.models.intraday_confirmation import IntradayConfirmationSnapshot as Snapshot


def test_upgrade_downgrade_models_and_single_head():
    root = Path(__file__).parents[2]
    path = root / "alembic/versions/0073_intraday_confirmation.py"
    spec = importlib.util.spec_from_file_location("intraday_revision", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0072_trend_periods"
    cfg = Config()
    cfg.set_main_option("script_location", str(root / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["0078_research_preview"]
    assert [r.revision for r in script.iterate_revisions("head", "0071_user_avatar")] == [
        "0078_research_preview", "0077_core_index_etf_sync", "0076_stock_strategies", "0075_watch_list_tags",
        "0074_industry_reference", "0073_intraday_confirmation", "0072_trend_periods",
    ]
    assert not (root / "alembic/versions/0072_intraday_confirmation.py").exists()
    ddl = str(CreateTable(Snapshot.__table__).compile(dialect=postgresql.dialect()))
    assert "JSONB" in ddl and "PRIMARY KEY (market, trade_date)" in ddl
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        actual = inspect(conn)
        assert {c["name"] for c in actual.get_columns(Snapshot.__tablename__)} == set(Snapshot.__table__.columns.keys())
        assert actual.get_pk_constraint(Snapshot.__tablename__)["constrained_columns"] == ["market", "trade_date"]
        assert {c["name"] for c in actual.get_check_constraints(Snapshot.__tablename__)} == {
            "ck_intraday_confirmation_market", "ck_intraday_confirmation_revision",
        }
        migration.downgrade()
        assert inspect(conn).get_table_names() == []
    engine.dispose()


def test_postgresql_upgrade_sql_orders_trend_then_intraday_without_a_database():
    import os
    import subprocess
    import sys
    root = Path(__file__).parents[2]
    env = {**os.environ, "DATABASE_URL": "postgresql+psycopg2://localhost/offline_migration_render",
           "PYTHONPATH": str(root / "src")}
    # Alembic env.py configures global logging. Isolate it so this graph regression
    # cannot disable application loggers for unrelated tests in the same pytest run.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"),
         "upgrade", "0071_user_avatar:head", "--sql"],
        cwd=root, env=env, check=True, capture_output=True, text=True, timeout=30,
    )
    sql = result.stdout
    assert sql.index("Running upgrade 0071_user_avatar -> 0072_trend_periods") < sql.index(
        "Running upgrade 0072_trend_periods -> 0073_intraday_confirmation"
    )
    assert sql.count("CREATE TABLE intraday_confirmation_snapshot") == 1
    assert "SET version_num='0073_intraday_confirmation'" in sql
