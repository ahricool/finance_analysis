"""Real isolated PostgreSQL migration/repository; offline HTTP fixtures."""

import importlib.util
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from finance_analysis.database.models.prediction_markets import PredictionEvent, PredictionTag
from finance_analysis.database.repositories.prediction_markets import Repository
from finance_analysis.prediction_markets.rules import project_event
from finance_analysis.prediction_markets.service import Service


@pytest.fixture
def repo():
    url = os.getenv("PREDICTION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires dedicated PREDICTION_TEST_DATABASE_URL")
    engine = create_engine(url)
    schema = "prediction_test_" + uuid4().hex
    with engine.begin() as c:
        c.execute(text(f"CREATE SCHEMA {schema}"))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    spec = importlib.util.spec_from_file_location(
        "prediction_migration", Path("alembic/versions/0091_prediction_markets.py")
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as c:
        c.execute(text(f"SET LOCAL search_path TO {schema}"))
        migration.op = Operations(MigrationContext.configure(c))
        migration.upgrade()
        assert set(inspect(c).get_table_names(schema=schema)) == {"prediction_tag", "prediction_event"}
        for model in (PredictionTag, PredictionEvent):
            assert {r["name"] for r in inspect(c).get_columns(model.__tablename__)} == set(
                model.__table__.columns.keys()
            )

    class DB:
        @contextmanager
        def get_session(self):
            with Session(scoped) as session:
                yield session

        @contextmanager
        def session_scope(self):
            with self.get_session() as session, session.begin():
                yield session

        def connect(self):
            return engine.connect()

    db = DB()
    try:
        yield Repository(db)
    finally:
        with engine.begin() as c:
            c.execute(text(f"SET LOCAL search_path TO {schema}"))
            migration.op = Operations(MigrationContext.configure(c))
            migration.downgrade()
            assert "prediction_event" not in inspect(c).get_table_names(schema=schema)
            c.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        engine.dispose()


def raw(title="Nvidia AMD semiconductors", **kwargs):
    return dict(
        id="1",
        slug="nvidia-event",
        title=title,
        description="export policy",
        tags=[{"id": "10"}, {"id": "11"}],
        **kwargs,
    )


def seed(repo):
    repo.upsert_tag(dict(id="10", slug="tech", label="Tech"))
    repo.upsert_tag(dict(id="11", slug="business", label="Business"))
    repo.upsert_tag(dict(id="12", slug="sports", label="Sports"))
    repo.upsert_event(project_event(raw()), repo.tags(admin=True))


def test_real_catalog_rule_overrides_or_filter_and_no_private_progress(repo):
    seed(repo)
    assert len(repo.tags()) == 2 and len(repo.tags(admin=True)) == 3
    assert repo.list_events(tag_ids=["10", "11"])["total"] == 1
    row = repo.list_events()["items"][0]
    assert not {"match_status", "match_progress", "links"} & row.keys()
    assert [t["slug"] for t in row["tags"]] == ["tech", "business"]
    repo.set_tag("10", False)
    repo.set_tag("11", False)
    assert repo.list_events()["total"] == 0
    repo.upsert_tag(dict(id="10", slug="tech", label="Tech"))
    assert repo.tags() == []
    repo.set_event("1", True)
    assert repo.list_events()["total"] == 1
    repo.set_event("1", False)
    repo.upsert_event(project_event(raw()), repo.tags(admin=True))
    assert repo.list_events()["total"] == 0
    assert repo.list_events(admin=True)["total"] == 1
    repo.set_event("1", None)
    repo.set_tag("10", None)
    assert repo.list_events()["total"] == 1


def test_catalog_dedup_partial_and_missing_is_not_closed(repo):
    seed(repo)

    class Upstream:
        def tags(self):
            yield dict(id="10", slug="tech", label="Tech")
            yield dict(id="11", slug="business", label="Business")

        def events(self, tag):
            yield raw(markets=[dict(outcomePrices=[".99"])])
            if tag == "11":
                raise RuntimeError("page interrupted")

        def event(self, event_id):
            raise RuntimeError("404")

    service = Service(repo=repo, client=Upstream())
    result = service.catalog()
    assert result["status"] == "partial" and result["deduplicated"] == 1
    assert repo.list_events()["total"] == 1
    assert repo.event("1")["closed"] is None
    service.client.events = lambda tag: iter([])
    assert service.catalog()["status"] == "partial"
    assert repo.event("1")["closed"] is None
    repo.upsert_event(project_event(raw(closed=True)), repo.tags(admin=True))
    assert repo.list_events()["total"] == 0
    assert repo.list_events(closed=True)["total"] == 1


def test_advisory_mutex_no_open_transaction(repo):
    from finance_analysis.tasks.advisory_lock import PostgreSQLAdvisoryLock

    a = PostgreSQLAdvisoryLock(19, db_manager=repo.db)
    b = PostgreSQLAdvisoryLock(19, db_manager=repo.db)
    assert a.acquire()
    assert not a.connection.in_transaction()
    try:
        assert not b.acquire()
    finally:
        a.release()
    assert b.acquire()
    b.release()


def test_catalog_uses_current_admin_rules_not_stale_snapshot(repo):
    seed(repo)
    old = repo.tags(admin=True)
    repo.set_tag("10", False)
    repo.set_tag("11", False)
    repo.upsert_event(project_event(raw()), old)
    assert repo.list_events()["total"] == 0


def test_dynamic_and_catalog_gets_execute_no_business_writes(repo, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import event as sql_event
    from finance_analysis.interfaces.api.v1.endpoints import prediction_markets as api
    from finance_analysis.interfaces.api.deps import require_current_user

    seed(repo)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.repository] = lambda: repo
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=7)

    class Live:
        def live(self, event_id):
            return dict(status="ready", markets=[])

        def history(self, *args):
            return dict(status="ready", points=[], changes={})

    monkeypatch.setattr(api, "get_live_service", lambda: Live())
    queries = []
    with repo.db.get_session() as s:
        engine = s.get_bind()

    def record(conn, cursor, statement, *args):
        queries.append(statement.lstrip().upper())

    sql_event.listen(engine, "before_cursor_execute", record)
    try:
        c = TestClient(app)
        for path in [
            "/tags",
            "/events",
            "/events/1/live",
            "/events/1/history?market_id=m&outcome_id=1",
        ]:
            assert c.get(path).status_code == 200
        assert queries and not any(q.startswith(("INSERT", "UPDATE", "DELETE")) for q in queries)
    finally:
        sql_event.remove(engine, "before_cursor_execute", record)
