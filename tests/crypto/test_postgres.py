"""Opt-in tests against an isolated PostgreSQL schema, never the application database."""

import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from finance_analysis.crypto.strategy import evaluate
from finance_analysis.database.models.crypto import CryptoKline, CryptoStrategySnapshot, CryptoStrategyState
from finance_analysis.database.repositories.crypto import CryptoRepository
from .helpers import candle


@pytest.mark.skipif(
    not os.getenv("CRYPTO_TEST_POSTGRES_URL"), reason="Requires a dedicated disposable PostgreSQL test DB"
)
def test_postgres_migration_decimal_idempotence_concurrent_evaluation_and_leader():
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
            for model in (CryptoKline, CryptoStrategySnapshot, CryptoStrategyState):
                assert set(c["name"] for c in inspect(conn).get_columns(model.__tablename__, schema=schema)) == set(
                    model.__table__.columns.keys()
                )
        repo = CryptoRepository(Database())
        rows = [candle(i) for i in range(15)]
        at = rows[-1].close_time
        repo.upsert_klines(rows, at)
        repo.upsert_klines(rows, at)
        actual = repo.klines(as_of=at)
        assert len(actual) == 15 and actual[0].volume == rows[0].volume
        assert actual[0].open_time == rows[0].open_time
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(lambda _: repo.evaluate_once(at, lambda state: evaluate(rows, at, state)), range(2))
            )
        assert sum(result is not None for result in results) == 1
        assert len(repo.signals()) == 1
        with repo.stream_leader() as first:
            assert first
            with repo.stream_leader() as second:
                assert not second
        with repo.stream_leader() as third:
            assert third
        with engine.begin() as conn:
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            migration.op = Operations(MigrationContext.configure(conn))
            migration.downgrade()
            assert inspect(conn).get_table_names(schema=schema) == []
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
