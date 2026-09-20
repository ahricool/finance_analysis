"""Opt-in tests against an isolated PostgreSQL schema, never the application database."""

import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from alembic.migration import MigrationContext
from alembic.operations import Operations
from finance_analysis.crypto.strategy import evaluate
from finance_analysis.database.models.crypto import CryptoStrategySnapshot, CryptoStrategyState
from finance_analysis.database.repositories.crypto import CryptoRepository

from .helpers import candle


@pytest.mark.skipif(
    not os.getenv("CRYPTO_TEST_POSTGRES_URL"), reason="Requires a dedicated disposable PostgreSQL test DB"
)
def test_postgres_migration_and_concurrent_evaluation():
    engine = create_engine(os.environ["CRYPTO_TEST_POSTGRES_URL"])
    schema = "crypto_test_" + uuid4().hex
    spec = importlib.util.spec_from_file_location(
        "crypto_pg_migration", Path(__file__).resolve().parents[2] / "alembic/versions/0044_crypto_btc.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    scoped = engine.execution_options(schema_translate_map={None: schema})

    class Database:
        @contextmanager
        def get_session(self):
            with Session(scoped) as session:
                yield session

        @contextmanager
        def session_scope(self):
            with Session(scoped) as session, session.begin():
                yield session

    try:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()
            position_spec = importlib.util.spec_from_file_location(
                "positions_pg", Path(__file__).resolve().parents[2] / "alembic/versions/0060_crypto_positions.py"
            )
            positions = importlib.util.module_from_spec(position_spec)
            position_spec.loader.exec_module(positions)
            positions.op = migration.op
            positions.upgrade()
            for model in (CryptoStrategySnapshot, CryptoStrategyState):
                assert set(c["name"] for c in inspect(conn).get_columns(model.__tablename__, schema=schema)) == set(
                    model.__table__.columns.keys()
                )
        repo = CryptoRepository(Database())
        rows = [candle(i) for i in range(15)]
        at = rows[-1].close_time
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(lambda _: repo.evaluate_once(at, lambda state: evaluate(rows, [], at, state)), range(2))
            )
        assert sum(result is not None for result in results) == 1
        assert len(repo.signals()) == 1

        def catchup(_):
            for index in range(15, 18):
                bar = candle(index)
                repo.evaluate_once(bar.close_time, lambda state: evaluate([bar], [], bar.close_time, state))

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(catchup, range(2)))
        assert len(repo.signals()) == 4
        assert repo.state().updated_at == candle(17).close_time
        with engine.begin() as conn:
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            migration.op = Operations(MigrationContext.configure(conn))
            drop_spec = importlib.util.spec_from_file_location(
                "crypto_drop_pg", Path(__file__).resolve().parents[2] / "alembic/versions/0059_drop_crypto_kline.py"
            )
            drop = importlib.util.module_from_spec(drop_spec)
            drop_spec.loader.exec_module(drop)
            drop.op = migration.op
            drop.upgrade()
            assert "crypto_kline" not in inspect(conn).get_table_names(schema=schema)
            assert conn.execute(text("SELECT count(*) FROM crypto_strategy_snapshot")).scalar() == 4
            drop.downgrade()
            positions.op = migration.op
            positions.downgrade()
            migration.downgrade()
            assert inspect(conn).get_table_names(schema=schema) == []
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
