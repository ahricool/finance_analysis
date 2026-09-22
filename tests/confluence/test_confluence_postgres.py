"""Real PostgreSQL migration, concurrent upsert and rollback in an isolated schema."""

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

from finance_analysis.confluence.engine import aggregate, signal
from finance_analysis.confluence.config import WEIGHTS
from finance_analysis.core.time import utc_now
from finance_analysis.database.models.confluence import ConfluenceRun, ConfluenceSnapshot
from finance_analysis.database.repositories.confluence import ConfluenceRepository


@pytest.mark.skipif(not os.getenv("CONFLUENCE_TEST_POSTGRES_URL"), reason="Requires isolated test PostgreSQL")
def test_postgres_migration_concurrent_upsert_and_rollback():
    engine = create_engine(os.environ["CONFLUENCE_TEST_POSTGRES_URL"])
    schema = "confluence_test_" + uuid4().hex
    scoped = engine.execution_options(schema_translate_map={None: schema})
    spec = importlib.util.spec_from_file_location(
        "migration", Path(__file__).parents[2] / "alembic/versions/0065_confluence.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    rules_spec = importlib.util.spec_from_file_location(
        "rules_migration", Path(__file__).parents[2] / "alembic/versions/0066_confluence_rules.py"
    )
    rules_migration = importlib.util.module_from_spec(rules_spec)
    rules_spec.loader.exec_module(rules_migration)

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
                    raise RuntimeError("injected")

    db = DB()
    repo = ConfluenceRepository(db)
    started = utc_now()
    day = date(2026, 9, 21)
    barrier = Barrier(2)
    row = dict(
        instrument_id=1,
        **aggregate({key: signal(key) for key in WEIGHTS}),
        generated_at=started,
        algorithm_version="v1",
    )
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(text("CREATE TABLE instrument (id INTEGER PRIMARY KEY)"))
            connection.execute(text("INSERT INTO instrument VALUES (1)"))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            rules_migration.op = migration.op
            rules_migration.upgrade()
            for model in (ConfluenceRun, ConfluenceSnapshot):
                assert {c["name"] for c in inspect(connection).get_columns(model.__tablename__, schema=schema)} == set(
                    model.__table__.c.keys()
                )

        def publish(i):
            barrier.wait(timeout=10)
            when = started + timedelta(seconds=i)
            return repo.save(
                "CN",
                day,
                [dict(row, generated_at=when)],
                dict(generated_at=when, algorithm_version="v1", source_availability={}),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(publish, [0, 1]))
        with db.get_session() as session:
            assert len(list(session.scalars(select(ConfluenceSnapshot)))) == 1
            assert session.get(ConfluenceRun, ("CN", day)).generated_at == started + timedelta(seconds=1)
        db.fail = True
        with pytest.raises(RuntimeError, match="injected"):
            repo.save(
                "CN",
                day,
                [],
                dict(generated_at=started + timedelta(seconds=2), algorithm_version="v1", source_availability={}),
            )
        with db.get_session() as session:
            assert len(list(session.scalars(select(ConfluenceSnapshot)))) == 1
        with engine.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            migration.op = Operations(MigrationContext.configure(connection))
            rules_migration.op = migration.op
            rules_migration.downgrade()
            migration.downgrade()
            assert not inspect(connection).has_table("confluence_run", schema=schema)
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
