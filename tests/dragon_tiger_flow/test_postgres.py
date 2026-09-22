"""Real migration and concurrent publication in a disposable PostgreSQL schema."""

import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.dragon_tiger_flow import DragonTigerFlowBatch as Batch
from finance_analysis.database.repositories.dragon_tiger_flow import DragonTigerFlowRepository
from finance_analysis.integrations.market_data.dragon_tiger import normalize_source


@pytest.mark.skipif(not os.getenv("DRAGON_TIGER_TEST_POSTGRES_URL"), reason="Requires disposable PostgreSQL test DB")
def test_postgres_migration_atomic_racing_publication_and_rollback():
    engine = create_engine(os.environ["DRAGON_TIGER_TEST_POSTGRES_URL"])
    schema = "dragon_test_" + uuid4().hex
    scoped = engine.execution_options(schema_translate_map={None: schema})
    spec = importlib.util.spec_from_file_location(
        "flow_migration", Path(__file__).parents[2] / "alembic/versions/0064_dragon_tiger_flow.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    class DB:
        fail = False

        @contextmanager
        def get_session(self):
            with Session(scoped) as session:
                yield session

        @contextmanager
        def session_scope(self):
            with Session(scoped) as session, session.begin():
                yield session
                session.flush()
                if self.fail:
                    raise RuntimeError("injected publication failure")

    db = DB()
    repo = DragonTigerFlowRepository(db)
    day = date(2026, 9, 21)
    source = normalize_source(
        {
            "trade_date": str(day),
            "board_type": "all",
            "timestamp": 1789920000000,
            "count": 0,
            "stock_count": 0,
            "stock_items": [],
            "hot_money_items": [],
        },
        day,
        "all",
    )
    started = utc_now()
    barrier = Barrier(2)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            assert {c["name"] for c in inspect(connection).get_columns(Batch.__tablename__, schema=schema)} == set(
                Batch.__table__.columns.keys()
            )

        def publish(i):
            barrier.wait(timeout=10)
            return repo.publish(day, {"all": source}, {}, started + timedelta(seconds=i))

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(publish, [0, 1]))
        assert all(r["status"] in ("completed", "superseded") for r in outcomes)
        with db.get_session() as session:
            batches = list(session.scalars(select(Batch)))
            assert len(batches) == 1
            assert batches[0].collected_at == started + timedelta(seconds=1)
            previous_id = batches[0].batch_id
        db.fail = True
        with pytest.raises(RuntimeError, match="injected"):
            repo.publish(day, {"all": source}, {}, started + timedelta(seconds=2))
        with db.get_session() as session:
            assert session.get(Batch, day).batch_id == previous_id
        with engine.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.downgrade()
            assert not inspect(connection).has_table(Batch.__tablename__, schema=schema)
            migration.upgrade()
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
