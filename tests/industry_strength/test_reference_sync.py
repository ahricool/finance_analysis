"""Weekly reference maintenance: real migration, atomic replacement and read-only consumers."""

import importlib.util
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session

from finance_analysis.database.models.industry_strength import IndustryCatalog, IndustryMembership
from finance_analysis.database.repositories.industry_strength import IndustryStrengthRepository
from finance_analysis.industry_strength.reference_sync import IndustryReferenceSyncService
from finance_analysis.industry_strength.service import IndustryReadinessError, IndustryStrengthService
from finance_analysis.tasks.celery.schedule import build_beat_schedule, build_task_routes, get_scheduled_task_definition

STAMP = datetime(2026, 10, 11, 2, tzinfo=timezone.utc)
CATALOG = [{"thscode": "881101.TI", "name": "煤炭"}, {"thscode": "881102.TI", "name": "农业"}]
MEMBERS = {r["thscode"]: [{"thscode": "600001.SH", "name": "示例股票"}] for r in CATALOG}


class Database:
    def __init__(self, bind=None):
        self.bind = bind if bind is not None else create_engine("sqlite://")

    @contextmanager
    def get_session(self):
        with Session(self.bind) as session:
            yield session

    @contextmanager
    def session_scope(self):
        with Session(self.bind) as session, session.begin():
            yield session


def migration():
    path = Path(__file__).parents[2] / "alembic/versions/0074_industry_reference.py"
    spec = importlib.util.spec_from_file_location("industry_reference_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repository():
    db = Database()
    with db.bind.begin() as conn:
        m = migration()
        m.op = Operations(MigrationContext.configure(conn))
        m.upgrade()
    return IndustryStrengthRepository(db)


def test_migration_matches_models_and_roundtrips():
    db = Database()
    m = migration()
    with db.bind.begin() as conn:
        m.op = Operations(MigrationContext.configure(conn))
        m.upgrade()
        schema = inspect(conn)
        for model in (IndustryCatalog, IndustryMembership):
            assert {c["name"] for c in schema.get_columns(model.__tablename__)} == set(model.__table__.columns.keys())
        assert schema.get_pk_constraint("industry_membership")["constrained_columns"] == ["industry_code", "stock_code"]
        assert schema.get_indexes("industry_membership")[0]["column_names"] == ["stock_code"]
        m.downgrade()
        assert not set(schema.get_table_names()).intersection({"industry_catalog", "industry_membership"})


def test_reference_generation_read_is_one_query_and_membership_needs_no_daily_snapshot(repository):
    repository.save_reference(CATALOG, MEMBERS, STAMP)
    queries = []
    def observe(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)
    event.listen(repository.db.bind, "before_cursor_execute", observe)
    catalog, members = repository.reference_data()
    assert len(queries) == 1
    assert members == MEMBERS
    assert [r["thscode"] for r in catalog] == [r["thscode"] for r in CATALOG]
    industries = repository.stock_memberships("600001.SH")
    assert [r["name"] for r in industries] == ["煤炭", "农业"]
    assert all(r["members_observed_at"].date() == STAMP.date() for r in industries)
    assert repository.stock_memberships("AAPL.US") == []
    queries.clear()
    assert repository.reference_data(include_members=False)[1] == {r["thscode"]: [] for r in CATALOG}
    assert len(queries) == 1 and "industry_membership" not in queries[0]


def test_replacement_removes_old_members_and_write_failure_restores_entire_generation(repository):
    repository.save_reference(CATALOG, MEMBERS, STAMP)
    previous = repository.reference_data()
    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO industry_membership"):
            raise RuntimeError("write failed")
    event.listen(repository.db.bind, "after_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="write failed"):
            repository.save_reference(CATALOG[:1], {"881101.TI": [{"thscode": "600002.SH", "name": "新股"}]}, STAMP)
    finally:
        event.remove(repository.db.bind, "after_cursor_execute", fail)
    assert repository.reference_data() == previous
    repository.save_reference(CATALOG[:1], {"881101.TI": [{"thscode": "600002.SH", "name": "新股"}]}, STAMP)
    assert repository.stock_memberships("600001.SH") == []
    assert len(repository.reference_data()[0]) == 1


def test_sync_collects_all_inputs_before_publish_and_preserves_old_reference_on_failure(repository):
    repository.save_reference(CATALOG, MEMBERS, STAMP)
    previous = repository.reference_data()
    calls = []
    def members(code):
        calls.append(code)
        if code == CATALOG[-1]["thscode"]:
            raise ValueError("source unavailable")
        return MEMBERS[code]
    data = SimpleNamespace(get_industry_catalog=lambda: CATALOG, get_index_constituents=members)
    with pytest.raises(ValueError, match="source unavailable"):
        IndustryReferenceSyncService(repository, data).run()
    assert calls == [r["thscode"] for r in CATALOG]
    assert repository.reference_data() == previous
    data.get_index_constituents = lambda code: MEMBERS[code]
    assert IndustryReferenceSyncService(repository, data).run()["industries"] == 2


@pytest.mark.parametrize("catalog,members", [([], {}), (CATALOG, {}), (CATALOG, {**MEMBERS, "881102.TI": []})])
def test_incomplete_generation_does_not_delete_existing_rows(repository, catalog, members):
    repository.save_reference(CATALOG, MEMBERS, STAMP)
    previous = repository.reference_data()
    with pytest.raises(ValueError):
        repository.save_reference(catalog, members, STAMP)
    assert repository.reference_data() == previous


def test_empty_reference_fails_before_any_market_request(repository, monkeypatch):
    service = IndustryStrengthService(repository, SimpleNamespace())
    monkeypatch.setattr(service, "sessions", lambda day: [])
    with pytest.raises(IndustryReadinessError, match="industry_reference_sync"):
        service.calculate(STAMP.date(), False)


def test_weekly_schedule_routes_and_manual_bootstrap():
    definition = get_scheduled_task_definition("industry_reference_sync")
    assert definition.queue == "ingestion" and definition.allow_manual_run
    schedule = definition.schedules[0]
    assert (schedule.day_of_week, schedule.hour, schedule.minute, schedule.timezone) == ("sun", "10", "0", "Asia/Shanghai")
    assert build_task_routes()[definition.celery_task_name]["queue"] == "ingestion"
    assert build_beat_schedule()[definition.job_id]["task"] == definition.celery_task_name


def test_postgresql_reference_publication_is_atomic():
    url = os.environ.get("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("dedicated TEST_POSTGRES_URL required")
    schema = "test_industry_reference_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as conn:
            m = migration()
            m.op = Operations(MigrationContext.configure(conn))
            m.upgrade()
        repo = IndustryStrengthRepository(Database(engine))
        repo.save_reference(CATALOG, MEMBERS, STAMP)
        previous = repo.reference_data()
        reads = []
        def observe(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith(("DELETE FROM industry_catalog", "INSERT INTO industry_membership")):
                reads.append(repo.reference_data())
        event.listen(engine, "after_cursor_execute", observe)
        try:
            repo.save_reference(CATALOG[:1], {"881101.TI": [{"thscode": "600002.SH", "name": "新成员"}]}, STAMP)
        finally:
            event.remove(engine, "after_cursor_execute", observe)
        assert len(reads) == 2 and all(value == previous for value in reads)
        assert repo.stock_memberships("600001.SH") == []
        assert repo.stock_memberships("600002.SH")[0]["members_observed_at"].tzinfo is not None
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()
