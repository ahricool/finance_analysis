import importlib.util
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from finance_analysis.database.models.crypto import CryptoKline, CryptoStrategySnapshot, CryptoStrategyState

ROOT = Path(__file__).resolve().parents[2]


def test_crypto_revision_single_head_upgrade_matches_orm_and_downgrade():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    assert ScriptDirectory.from_config(config).get_current_head() == "0044_crypto_btc"
    spec = importlib.util.spec_from_file_location("crypto_migration", ROOT / "alembic/versions/0044_crypto_btc.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with create_engine("sqlite://").begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        inspector = inspect(connection)
        for model in (CryptoKline, CryptoStrategyState, CryptoStrategySnapshot):
            columns = {col["name"]: col for col in inspector.get_columns(model.__tablename__)}
            assert set(columns) == set(model.__table__.columns.keys())
            if "price" in columns:
                assert columns["price"]["type"].scale == 12
        assert inspector.get_unique_constraints("crypto_kline")[0]["column_names"] == [
            "symbol",
            "interval",
            "open_time",
        ]
        migration.downgrade()
        assert inspect(connection).get_table_names() == []
