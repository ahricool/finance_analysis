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
    path = root / "alembic/versions/0072_intraday_confirmation.py"
    spec = importlib.util.spec_from_file_location("intraday_revision", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0071_user_avatar"
    cfg = Config()
    cfg.set_main_option("script_location", str(root / "alembic"))
    assert ScriptDirectory.from_config(cfg).get_heads() == ["0072_intraday_confirmation"]
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
