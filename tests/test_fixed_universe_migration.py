from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from finance_analysis.core.paths import PROJECT_ROOT
from finance_analysis.database.session import DatabaseManager


def _load_migration() -> ModuleType:
    path = Path(PROJECT_ROOT) / "alembic" / "versions" / "0023_fixed_quant_universes.py"
    spec = importlib.util.spec_from_file_location("fixed_quant_universe_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="PostgreSQL required")
def test_fixed_universe_migration_preserves_ids_and_leaves_member_rows_untouched() -> None:
    migration = _load_migration()
    database = DatabaseManager.get_instance()
    schema = f"fixed_universe_{uuid.uuid4().hex}"

    with database._engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(
                text(
                    """
                    CREATE TABLE quant_universe (
                        id INTEGER PRIMARY KEY,
                        key VARCHAR(64) NOT NULL UNIQUE,
                        name VARCHAR(128) NOT NULL,
                        market VARCHAR(8) NOT NULL,
                        description TEXT,
                        enabled BOOLEAN NOT NULL,
                        is_dynamic BOOLEAN NOT NULL,
                        benchmark_code VARCHAR(32),
                        sector_benchmark_mode VARCHAR(32) NOT NULL,
                        config JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE market_data_symbol (
                        id INTEGER PRIMARY KEY,
                        code VARCHAR(32) NOT NULL
                    );
                    CREATE TABLE quant_universe_member (
                        id BIGINT PRIMARY KEY,
                        universe_id INTEGER NOT NULL,
                        symbol_id INTEGER NOT NULL,
                        effective_from DATE NOT NULL,
                        effective_to DATE,
                        enabled BOOLEAN NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE quant_dataset_snapshot (
                        id BIGINT PRIMARY KEY,
                        universe_id INTEGER NOT NULL REFERENCES quant_universe(id)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO quant_universe
                        (id, key, name, market, enabled, is_dynamic, sector_benchmark_mode, config)
                    VALUES
                        (42, 'us_sp500_watchlist', 'old', 'US', true, true, 'member', '{}'),
                        (99, 'us_ai_semiconductor', 'old unsupported', 'US', true, true, 'member', '{}');
                    INSERT INTO market_data_symbol (id, code)
                    VALUES (1, 'AAPL.US'), (2, 'WATCHLIST-ONLY.US');
                    INSERT INTO quant_universe_member
                        (id, universe_id, symbol_id, effective_from, enabled)
                    VALUES
                        (1, 42, 1, '2020-01-01', true),
                        (2, 42, 2, '2020-01-01', true);
                    INSERT INTO quant_dataset_snapshot (id, universe_id) VALUES (7, 42)
                    """
                )
            )
            migration.op = Operations(MigrationContext.configure(connection))

            migration.upgrade()

            universe = connection.execute(
                text(
                    "SELECT id, key, name, is_dynamic, sector_benchmark_mode, config FROM quant_universe "
                    "WHERE id = 42"
                )
            ).mappings().one()
            assert universe["id"] == 42
            assert universe["key"] == "us_sp500"
            assert universe["name"] == "S&P 500"
            assert universe["is_dynamic"] is False
            assert universe["sector_benchmark_mode"] == "market_dependencies"
            assert universe["config"] == {"constituent_source": "SP500_STOCK_INDEX"}
            assert connection.execute(
                text("SELECT universe_id FROM quant_dataset_snapshot WHERE id = 7")
            ).scalar_one() == 42
            active = connection.execute(
                text(
                    "SELECT symbol.code FROM quant_universe_member AS member "
                    "JOIN market_data_symbol AS symbol ON symbol.id = member.symbol_id "
                    "WHERE member.enabled = true AND member.effective_to IS NULL"
                )
            ).scalars().all()
            assert active == ["AAPL.US", "WATCHLIST-ONLY.US"]
            effective_to = connection.execute(
                text(
                    "SELECT effective_to FROM quant_universe_member "
                    "WHERE symbol_id = 2"
                )
            ).scalar_one()
            assert effective_to is None
            assert connection.execute(
                text("SELECT enabled FROM quant_universe WHERE id = 99")
            ).scalar_one() is False

            migration.downgrade()
            restored = connection.execute(
                text("SELECT id, key FROM quant_universe WHERE id = 42")
            ).mappings().one()
            assert dict(restored) == {"id": 42, "key": "us_sp500_watchlist"}
        finally:
            transaction.rollback()
