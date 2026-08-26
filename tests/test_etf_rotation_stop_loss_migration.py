from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError

from finance_analysis.core.paths import PROJECT_ROOT


def _load_migration():
    path = Path(PROJECT_ROOT) / "alembic" / "versions" / "0029_etf_rotation_stop_loss.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stop_loss_migration_keeps_history_null_and_enforces_constraints() -> None:
    migration = _load_migration()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE etf_momentum_snapshot (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO etf_momentum_snapshot (id) VALUES (1)"))
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()

        columns = {column["name"]: column for column in inspect(connection).get_columns("etf_momentum_snapshot")}
        assert {"reference_price", "stop_loss_pct", "suggested_stop_price"} <= set(columns)
        assert all(columns[name]["nullable"] for name in ("reference_price", "stop_loss_pct", "suggested_stop_price"))
        historical = connection.execute(
            text("SELECT reference_price, stop_loss_pct, suggested_stop_price FROM etf_momentum_snapshot")
        ).one()
        assert historical == (None, None, None)
        checks = {item["name"] for item in inspect(connection).get_check_constraints("etf_momentum_snapshot")}
        assert {
            "ck_etf_reference_price_positive",
            "ck_etf_stop_loss_pct_range",
            "ck_etf_suggested_stop_price_positive",
            "ck_etf_stop_loss_metadata_complete",
        } <= checks
        connection.execute(
            text(
                "INSERT INTO etf_momentum_snapshot "
                "(id, reference_price, stop_loss_pct, suggested_stop_price) VALUES (2, 100, 0.05, 95)"
            )
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO etf_momentum_snapshot "
                    "(id, reference_price, stop_loss_pct, suggested_stop_price) VALUES (3, 100, 1.1, 95)"
                )
            )


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="PostgreSQL required")
def test_stop_loss_migration_runs_on_postgresql() -> None:
    migration = _load_migration()
    engine = create_engine(os.environ["DATABASE_URL"])
    schema = f"etf_rotation_stop_{uuid.uuid4().hex}"
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
            connection.execute(text("CREATE TABLE etf_momentum_snapshot (id BIGINT PRIMARY KEY)"))
            connection.execute(text("INSERT INTO etf_momentum_snapshot (id) VALUES (1)"))
            migration.op = Operations(MigrationContext.configure(connection))

            migration.upgrade()

            assert connection.execute(
                text("SELECT reference_price, stop_loss_pct, suggested_stop_price FROM etf_momentum_snapshot")
            ).one() == (None, None, None)
            checks = {item["name"] for item in inspect(connection).get_check_constraints("etf_momentum_snapshot")}
            assert {
                "ck_etf_reference_price_positive",
            "ck_etf_stop_loss_pct_range",
            "ck_etf_suggested_stop_price_positive",
            "ck_etf_stop_loss_metadata_complete",
            } <= checks
            savepoint = connection.begin_nested()
            try:
                with pytest.raises(IntegrityError):
                    connection.execute(
                        text(
                            "INSERT INTO etf_momentum_snapshot "
                            "(id, reference_price, stop_loss_pct, suggested_stop_price) "
                            "VALUES (2, 100, 0.05, 101)"
                        )
                    )
            finally:
                savepoint.rollback()
        finally:
            transaction.rollback()
            engine.dispose()
