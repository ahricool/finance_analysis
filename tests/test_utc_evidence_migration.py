"""Exercise the historical JSON repair in PostgreSQL, including DST and reruns."""

import os

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="requires PostgreSQL")
def test_normalizes_macro_cutoffs_without_shifting_the_instant(monkeypatch):
    migration = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("0104_utc_evidence_cutoff").module
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL TIME ZONE 'America/New_York'")
        for table, column in (("confluence_run", "source_availability"), ("confluence_snapshot", "signals")):
            connection.exec_driver_sql(f"CREATE TEMP TABLE {table} ({column} jsonb) ON COMMIT DROP")
            connection.execute(text(f"""
                INSERT INTO {table}
                SELECT jsonb_build_object('macro', jsonb_build_object('evidence',
                    jsonb_build_object('cutoff', stamp)), 'source', stamp)
                FROM unnest(ARRAY['2026-06-02T00:30:00.123456+08:00',
                                  '2026-11-01T01:30:00-04:00', '2026-11-01T01:30:00-05:00']) t(stamp)
            """))
            connection.exec_driver_sql(f"INSERT INTO {table} VALUES ('{{}}')")
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.upgrade()
        for table, column in (("confluence_run", "source_availability"), ("confluence_snapshot", "signals")):
            rows = connection.exec_driver_sql(f"SELECT {column} FROM {table}").scalars().all()
            assert {} in rows
            assert sorted(row["macro"]["evidence"]["cutoff"] for row in rows if row) == [
                "2026-06-01T16:30:00.123456Z", "2026-11-01T05:30:00.000000Z", "2026-11-01T06:30:00.000000Z"
            ]
            assert all(row["source"][-6] in "+-" for row in rows if row)
    engine.dispose()
