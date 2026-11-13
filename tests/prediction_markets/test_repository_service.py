"""Real isolated PostgreSQL migration/repository; offline HTTP/LLM fixtures."""

import importlib.util
import json
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

from finance_analysis.database.models.prediction_markets import PredictionEvent, PredictionTag, PredictionInstrumentLink
from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.repositories.prediction_markets import Repository
from finance_analysis.prediction_markets.config import Config
from finance_analysis.prediction_markets.rules import project_event, digest, matching_version
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
    Instrument.__table__.create(scoped)
    spec = importlib.util.spec_from_file_location(
        "prediction_migration", Path("alembic/versions/0091_prediction_markets.py")
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as c:
        c.execute(text(f"SET LOCAL search_path TO {schema}"))
        migration.op = Operations(MigrationContext.configure(c))
        migration.upgrade()
        for model in (PredictionTag, PredictionEvent, PredictionInstrumentLink):
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
    with db.session_scope() as s:
        s.add_all(
            [
                Instrument(code=code, name=name, market=market)
                for code, name, market in [
                    ("NVDA.US", "Nvidia", "US"),
                    ("AMD.US", "AMD", "US"),
                    ("700.HK", "腾讯", "HK"),
                ]
            ]
        )
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


def profile(symbol, name):
    return dict(symbol=symbol, name=name, aliases=[], industries=[])


class LLM:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or {"event_id": "1", "associations": []}

    def complete_text(self, request, validator):
        self.calls.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        output = json.dumps(self.response)
        validator(output)
        return SimpleNamespace(text=output)


def test_real_catalog_rule_overrides_or_filter_and_no_private_progress(repo):
    seed(repo)
    assert len(repo.tags()) == 2 and len(repo.tags(admin=True)) == 3
    assert repo.list_events(tag_ids=["10", "11"])["total"] == 1
    row = repo.list_events()["items"][0]
    assert row["match_status"] == "pending" and "match_progress" not in row
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


def test_empty_match_cached_new_stock_only_and_failure_distinct(repo):
    seed(repo)
    profiles = [profile("NVDA.US", "Nvidia")]
    repo.profiles = lambda _: profiles
    llm = LLM()
    service = Service(repo=repo, client=object(), llm=llm, config=Config(enabled=True, candidate_group_size=1))
    assert service.match()["no_match"] == 1
    assert repo.event("1")["match_status"] == "no_match"
    assert service.match()["cached"] == 1 and len(llm.calls) == 1
    profiles.append(profile("AMD.US", "AMD"))
    assert service.match()["no_match"] == 1 and len(llm.calls) == 2
    assert "NVDA.US" not in llm.calls[-1].prompt and "AMD.US" in llm.calls[-1].prompt
    assert all(not r.web_search and r.call_type == "polymarket_stock_matching" and r.uid is None for r in llm.calls)
    repo.upsert_event(project_event(raw(title="Nvidia AMD tariffs revised")), repo.tags(admin=True))
    llm.response = RuntimeError("offline failure")
    assert service.match()["failed"] == 1
    assert repo.event("1")["match_status"] == "failed"
    assert service.match()["pending"] == 1
    assert repo.list_events()["total"] == 1


def test_group_publish_manual_precedence_old_version_and_delayed_cleanup(repo):
    seed(repo)
    e = repo.event("1")
    version = matching_version(e, repo.tags(admin=True))
    nv, amd = profile("NVDA.US", "Nvidia"), profile("AMD.US", "AMD")

    def answer(symbol):
        return dict(symbol=symbol, relation_type="industry", relevance="high", reason="出口限制影响市场")

    assert repo.publish_group("1", e["semantic_hash"], version, [nv], [answer("NVDA.US")])
    assert repo.publish_group("1", e["semantic_hash"], version, [amd], [answer("AMD.US")])
    assert len(repo.list_events()["items"][0]["links"]) == 2
    repo.set_link("1", "NVDA.US", "block")
    repo.publish_group("1", e["semantic_hash"], version, [nv], [answer("NVDA.US")])
    assert len(repo.list_events()["items"][0]["links"]) == 1
    repo.set_link("1", "700.HK", "add", reason="人工港股关联")
    assert repo.list_events(symbol="700.HK")["total"] == 1
    repo.upsert_event(project_event(raw(title="Nvidia new policy")), repo.tags(admin=True))
    assert not repo.publish_group("1", e["semantic_hash"], version, [amd], [])
    assert len(repo.list_events()["items"][0]["links"]) == 2
    e2 = repo.event("1")
    v2 = matching_version(e2, repo.tags(admin=True))
    assert not repo.finish_matching("1", e2["semantic_hash"], v2, [nv, amd], [nv, amd])
    assert len(repo.list_events()["items"][0]["links"]) == 2
    assert repo.publish_group("1", e2["semantic_hash"], v2, [nv], [])
    assert repo.finish_matching("1", e2["semantic_hash"], v2, [nv, amd], [nv])
    assert [l["symbol"] for l in repo.list_events()["items"][0]["links"]] == ["700.HK"]
    repo.set_link("1", "NVDA.US", "restore")
    assert "NVDA.US" not in repo.event("1")["match_progress"]


def test_catalog_dedup_partial_and_missing_is_not_closed(repo):
    seed(repo)
    repo.profiles = lambda _: []

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

    llm = LLM()
    service = Service(repo=repo, client=Upstream(), llm=llm, config=Config(enabled=True))
    result = service.catalog()
    assert result["status"] == "partial" and result["deduplicated"] == 1
    assert len(llm.calls) == 0 and repo.list_events()["total"] == 1
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


def test_tag_label_changes_invalidate_empty_matching_and_old_call(repo):
    seed(repo)
    profiles = [profile("NVDA.US", "Nvidia")]
    repo.profiles = lambda _: profiles
    llm = LLM()
    service = Service(repo=repo, client=object(), llm=llm, config=Config(enabled=True))
    service.match()
    e = repo.event("1")
    old_version = matching_version(e, repo.tags(admin=True))
    repo.upsert_tag(dict(id="10", slug="tech", label="Technology renamed"))
    assert not repo.publish_group("1", e["semantic_hash"], old_version, profiles, [])
    assert service.match()["no_match"] == 1 and len(llm.calls) == 2
    assert service.match()["cached"] == 1


def test_profile_change_inside_publish_transaction_rejects_stale_result(repo):
    seed(repo)
    e = repo.event("1")
    version = matching_version(e, repo.tags(admin=True))
    old = profile("NVDA.US", "Nvidia")
    with repo.db.session_scope() as s:
        instrument = s.query(Instrument).filter_by(code="NVDA.US").one()
        instrument.instrument_metadata = {"aliases": ["NVIDIA Corporation"]}
    assert not repo.publish_group("1", e["semantic_hash"], version, [old], [])


def test_public_pool_union_excludes_private_fields_hk_and_closed_positions(repo):
    from finance_analysis.core.time import utc_now
    from finance_analysis.database.models.watch_list import WatchListItem
    from finance_analysis.database.models.portfolio import PortfolioAccount, PortfolioPosition
    from finance_analysis.database.models.industry_strength import IndustryCatalog, IndustryMembership

    with repo.db.get_session() as session:
        engine = session.get_bind()
    for model in (WatchListItem, PortfolioAccount, PortfolioPosition, IndustryCatalog, IndustryMembership):
        model.__table__.create(engine)
    with repo.db.session_scope() as s:
        s.add_all(
            [
                WatchListItem(uid=1, code="NVDA.US", market_type="US", notes="private secret"),
                WatchListItem(uid=2, code="NVDA.US", market_type="US", notes="another owner"),
                WatchListItem(uid=2, code="700.HK", market_type="HK"),
            ]
        )
        s.add(PortfolioAccount(id=1, uid=9, market="US", name="private account", cash=12345))
        s.flush()
        s.add(
            PortfolioPosition(
                uid=9, account_id=1, market="US", symbol="AMD.US", quantity=123, average_cost=999, opened_at=utc_now()
            )
        )
    profiles = repo.profiles()
    assert {p["symbol"] for p in profiles} == {"NVDA.US", "AMD.US"}
    assert all(set(p) == {"symbol", "name", "aliases", "industries"} for p in profiles)
    assert all(value not in json.dumps(profiles) for value in ["private", "quantity", "average_cost", "uid"])
    with repo.db.session_scope() as s:
        s.query(PortfolioPosition).update({"quantity": 0})
    assert {p["symbol"] for p in repo.profiles()} == {"NVDA.US"}


def test_catalog_same_input_preserves_failure_backoff(repo):
    seed(repo)
    profiles = [profile("NVDA.US", "Nvidia")]
    repo.profiles = lambda _: profiles
    service = Service(repo=repo, client=object(), llm=LLM(RuntimeError("failed")), config=Config(enabled=True))
    service.match()
    retry_at = repo.event("1")["retry_at"]
    repo.mark_pending(profiles)
    assert repo.event("1")["retry_at"] == retry_at
    repo.mark_pending([*profiles, profile("AMD.US", "AMD")])
    assert repo.event("1")["retry_at"] is None


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
    monkeypatch.setattr(api, "get_config", lambda: Config(enabled=True))

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
            "/stocks/NVDA.US",
            "/events/1/live",
            "/events/1/history?market_id=m&outcome_id=1",
        ]:
            assert c.get(path).status_code == 200
        assert queries and not any(q.startswith(("INSERT", "UPDATE", "DELETE")) for q in queries)
    finally:
        sql_event.remove(engine, "before_cursor_execute", record)
