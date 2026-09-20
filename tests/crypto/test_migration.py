import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from finance_analysis.database.models.crypto import CryptoStrategySnapshot, CryptoStrategyState

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("position, expected_pct, expected_average", [("LONG", 1, 123), ("FLAT", 0, None)])
def test_crypto_revision_single_head_upgrade_matches_orm_and_downgrade(position, expected_pct, expected_average):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    head = scripts.get_current_head()
    assert head and {
        "0044_crypto_btc",
        "0059_drop_crypto_kline",
        "0060_crypto_positions",
        "0061_crypto_strategy_keys",
    } <= {revision.revision for revision in scripts.walk_revisions(head=head)}
    spec = importlib.util.spec_from_file_location("crypto_migration", ROOT / "alembic/versions/0044_crypto_btc.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with create_engine("sqlite://").begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
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
        position_spec = importlib.util.spec_from_file_location(
            "positions", ROOT / "alembic/versions/0060_crypto_positions.py"
        )
        positions = importlib.util.module_from_spec(position_spec)
        position_spec.loader.exec_module(positions)
        positions.op = migration.op
        connection.exec_driver_sql("UPDATE crypto_strategy_state SET position_state=?, entry_price=123", (position,))
        drop.upgrade()
        positions.upgrade()
        key_spec = importlib.util.spec_from_file_location(
            "keys", Path(__file__).resolve().parents[2] / "alembic/versions/0061_crypto_strategy_keys.py"
        )
        keys = importlib.util.module_from_spec(key_spec)
        key_spec.loader.exec_module(keys)
        keys.op = migration.op
        keys.upgrade()
        assert inspect(migration.op.get_bind()).get_pk_constraint("crypto_strategy_state")["constrained_columns"] == [
            "strategy_key",
            "symbol",
        ]
        assert connection.exec_driver_sql(
            "SELECT position_pct, average_entry_price FROM crypto_strategy_state"
        ).one() == (expected_pct, expected_average)
        assert connection.exec_driver_sql(
            "SELECT position_before,position_after,position_delta,average_entry_price FROM crypto_strategy_snapshot"
        ).one() == (None, 1, None, None)
        for table in ("crypto_strategy_state", "crypto_strategy_snapshot"):
            assert connection.exec_driver_sql(f"SELECT strategy_key FROM {table}").scalar() == "btc_breakout_v1"
        assert inspect(connection).get_unique_constraints("crypto_strategy_snapshot")[0]["column_names"] == [
            "strategy_key",
            "symbol",
            "evaluated_at",
        ]
        connection.exec_driver_sql("UPDATE crypto_strategy_state SET strategy_key='btc_test_v1'")
        with pytest.raises(ValueError, match="other strategy"):
            keys.downgrade()
        connection.exec_driver_sql("UPDATE crypto_strategy_state SET strategy_key='btc_breakout_v1'")
        inspector = inspect(connection)
        for model in (CryptoStrategyState, CryptoStrategySnapshot):
            columns = {col["name"]: col for col in inspector.get_columns(model.__tablename__)}
            assert set(columns) == set(model.__table__.columns.keys())
            assert columns["strategy_key"]["default"] is None
            if "price" in columns:
                assert columns["price"]["type"].scale == 12
        assert "crypto_kline" not in inspect(connection).get_table_names()
        assert connection.exec_driver_sql("SELECT position_state FROM crypto_strategy_state").scalar() == position
        assert connection.exec_driver_sql("SELECT action FROM crypto_strategy_snapshot").scalar() == "BUY"
        from finance_analysis.database.base import Base

        assert "crypto_kline" not in Base.metadata.tables
        keys.op = migration.op
        keys.downgrade()
        positions.downgrade()
        drop.downgrade()
        assert "crypto_kline" in inspect(connection).get_table_names()
        migration.downgrade()
        assert inspect(connection).get_table_names() == []
