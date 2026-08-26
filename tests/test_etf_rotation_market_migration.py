from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import OperationalError

from finance_analysis.core.paths import PROJECT_ROOT


def _load_migration():
    path = Path(PROJECT_ROOT) / "alembic" / "versions" / "0028_etf_rotation_market.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="PostgreSQL required")
def test_market_migration_backfills_cn_and_enforces_schema() -> None:
    migration = _load_migration()
    engine = create_engine(os.environ["DATABASE_URL"])
    schema = f"etf_rotation_market_{uuid.uuid4().hex}"
    try:
        connection_context = engine.connect()
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL is unavailable: {exc.orig}")
    with connection_context as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(
                text(
                    "CREATE TABLE etf_momentum_snapshot ("
                    "id BIGINT PRIMARY KEY, trade_date DATE NOT NULL, symbol_id INTEGER NOT NULL, "
                    "entry_score FLOAT NOT NULL, is_candidate BOOLEAN NOT NULL, candidate_rank INTEGER)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_etf_momentum_snapshot_date_entry "
                    "ON etf_momentum_snapshot (trade_date, entry_score)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_etf_momentum_snapshot_date_candidate "
                    "ON etf_momentum_snapshot (trade_date, is_candidate, candidate_rank)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO etf_momentum_snapshot "
                    "(id, trade_date, symbol_id, entry_score, is_candidate) "
                    "VALUES (1, '2026-08-26', 1, 80, false)"
                )
            )
            migration.op = Operations(MigrationContext.configure(connection))

            migration.upgrade()

            assert connection.execute(text("SELECT market FROM etf_momentum_snapshot")).scalar_one() == "CN"
            market_column = next(
                column
                for column in inspect(connection).get_columns("etf_momentum_snapshot")
                if column["name"] == "market"
            )
            assert market_column["nullable"] is False
            checks = {item["name"] for item in inspect(connection).get_check_constraints("etf_momentum_snapshot")}
            indexes = {item["name"] for item in inspect(connection).get_indexes("etf_momentum_snapshot")}
            assert "ck_etf_momentum_snapshot_market" in checks
            assert "ix_etf_momentum_snapshot_market_date_entry" in indexes
            assert "ix_etf_momentum_snapshot_market_date_candidate" in indexes
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO etf_momentum_snapshot "
                        "(id, market, trade_date, symbol_id, entry_score, is_candidate) "
                        "VALUES (2, 'HK', '2026-08-26', 2, 70, false)"
                    )
                )
        finally:
            transaction.rollback()
            engine.dispose()
