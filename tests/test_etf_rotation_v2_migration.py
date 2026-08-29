from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from finance_analysis.core.paths import PROJECT_ROOT


def test_v2_migration_keeps_historical_factor_columns_nullable_and_creates_market_snapshot() -> None:
    path = Path(PROJECT_ROOT) / "alembic" / "versions" / "0030_etf_rotation_v2.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE etf_momentum_snapshot (id INTEGER PRIMARY KEY, market VARCHAR(8), trade_date DATE)"
        ))
        connection.execute(
            text("INSERT INTO etf_momentum_snapshot (id, market, trade_date) VALUES (1, 'CN', '2026-08-28')")
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        columns = {column["name"]: column for column in inspect(connection).get_columns("etf_momentum_snapshot")}
        assert columns["composite_score"]["nullable"] is True
        assert columns["weighted_slope_25d"]["nullable"] is True
        assert columns["action"]["nullable"] is True
        assert connection.execute(text(
            "SELECT composite_score, weighted_slope_25d, action, diagnostics FROM etf_momentum_snapshot"
        )).one() == (None, None, None, "{}")
        assert "etf_market_rotation_snapshot" in inspect(connection).get_table_names()
        indexes = {item["name"] for item in inspect(connection).get_indexes("etf_momentum_snapshot")}
        assert "ix_etf_momentum_snapshot_market_date_composite" in indexes
