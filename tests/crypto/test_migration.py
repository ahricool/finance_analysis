import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, inspect

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from finance_analysis.database.models.crypto import CryptoStrategySnapshot, CryptoStrategyState

ROOT = Path(__file__).resolve().parents[2]


def test_crypto_revision_single_head_upgrade_matches_orm_and_downgrade():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    head = scripts.get_current_head()
    assert head and {"0044_crypto_btc", "0059_drop_crypto_kline"} <= {
        revision.revision for revision in scripts.walk_revisions(head=head)
    }
    spec = importlib.util.spec_from_file_location("crypto_migration", ROOT / "alembic/versions/0044_crypto_btc.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with create_engine("sqlite://").begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        inspector = inspect(connection)
        for model in (CryptoStrategyState, CryptoStrategySnapshot):
            columns = {col["name"]: col for col in inspector.get_columns(model.__tablename__)}
            assert set(columns) == set(model.__table__.columns.keys())
            if "price" in columns:
                assert columns["price"]["type"].scale == 12
        drop_spec = importlib.util.spec_from_file_location(
            "drop_crypto", ROOT / "alembic/versions/0059_drop_crypto_kline.py"
        )
        drop = importlib.util.module_from_spec(drop_spec)
        drop_spec.loader.exec_module(drop)
        drop.op = migration.op
        connection.exec_driver_sql(
            "INSERT INTO crypto_strategy_state (symbol, position_state, updated_at) VALUES ('BTCUSDT', 'FLAT', CURRENT_TIMESTAMP)"
        )
        connection.exec_driver_sql(
            "INSERT INTO crypto_strategy_snapshot "
            "(symbol, evaluated_at, regime, setup, action, price, position_state, reason, created_at) "
            "VALUES ('BTCUSDT', CURRENT_TIMESTAMP, 'BULL', 'BREAKOUT', 'BUY', 100, 'LONG', 'test', CURRENT_TIMESTAMP)"
        )
        drop.upgrade()
        assert "crypto_kline" not in inspect(connection).get_table_names()
        assert connection.exec_driver_sql("SELECT position_state FROM crypto_strategy_state").scalar() == "FLAT"
        assert connection.exec_driver_sql("SELECT action FROM crypto_strategy_snapshot").scalar() == "BUY"
        from finance_analysis.database.base import Base

        assert "crypto_kline" not in Base.metadata.tables
        drop.downgrade()
        assert "crypto_kline" in inspect(connection).get_table_names()
        migration.downgrade()
        assert inspect(connection).get_table_names() == []
