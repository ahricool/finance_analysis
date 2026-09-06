"""Investment timeline contracts and persistence boundaries (offline)."""

from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from finance_analysis.database.base import Base
from finance_analysis.database.models.market_calendar import FinanceEvent
from finance_analysis.database.models.news import NewsIntel, NewsIntelUsage
from finance_analysis.database.models.news_analysis import NewsAnalysis
from finance_analysis.database.models.timeline import TimelineEntry
from finance_analysis.database.repositories.news_analysis import NewsAnalysisRepo
from finance_analysis.database.repositories.timeline import TimelineEntryRepo
from finance_analysis.database.session import DatabaseManager
from finance_analysis.timeline.service import TimelineService
from finance_analysis.timeline.cursor import TimelineCursor

NOW = datetime(2026, 9, 6, 8, tzinfo=timezone.utc)
QUERY = dict(uid=7, start_date=date(2026, 9, 6), end_date=date(2026, 9, 6), timezone_name="Asia/Shanghai")


class TestDB:
    __test__ = False

    def __init__(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        for model in (NewsIntel, NewsIntelUsage, NewsAnalysis, TimelineEntry, FinanceEvent):
            model.__table__.create(self.engine)

    @contextmanager
    def get_session(self):
        with Session(self.engine, expire_on_commit=False) as session:
            yield session

    def _run_write_transaction(self, name, callback):
        with self.get_session() as session, session.begin():
            return callback(session)


@pytest.fixture
def db():
    return TestDB()


def report(db, **overrides):
    values = dict(
        uid=7,
        entry_type="us_premarket",
        market="US",
        event_time=NOW,
        title="盘前分析",
        summary="等待趋势确认。",
        content="# Full report",
        importance="high",
        actionability="consider",
    )
    return TimelineEntryRepo(db).create(**(values | overrides))


def seed_news(db, score=9, url="https://example.com/news"):
    db._run_write_transaction(
        "seed",
        lambda session: session.add(
            NewsIntel(title="芯片需求", snippet="订单增长", url=url, published_date=NOW, fetched_at=NOW)
        ),
    )
    repo = NewsAnalysisRepo(db)
    repo.persist_premarket(
        [
            dict(
                news_id_or_url=url,
                importance_score=score,
                importance_reason="盈利驱动",
                related_symbols=["NVDA", "AMD"],
                event_type="guidance",
                confidence=0.8,
            )
        ],
        [
            dict(
                news_id_or_url=url,
                impact="bullish",
                impact_score=3,
                confidence=0.7,
                reason="需求上升",
                watch_points=["订单"],
                risk_notes=["估值"],
            )
        ],
        model="test",
        analyzed_at=NOW,
    )


def test_deleted_calendar_model_and_intraday_persistence():
    assert "calendar" not in Base.metadata.tables
    import finance_analysis.database.models as models

    assert not hasattr(models, "CalendarEntry")
    root = Path(__file__).resolve().parents[1] / "src/finance_analysis"
    assert not (root / "database/repositories/calendar.py").exists()
    for job in ("a_share_intraday_analysis", "us_intraday_analysis"):
        source = "\n".join(p.read_text() for p in (root / "tasks/celery/jobs" / job).glob("*.py"))
        for forbidden in (
            "CalendarRepo",
            "calendar_id",
            "record_summary",
            "record_signal",
            "TimelineEntry",
            "NewsAnalysis",
        ):
            assert forbidden not in source


def test_note_crud_is_owner_scoped_and_cannot_edit_reports(db):
    repo = TimelineEntryRepo(db)
    note = report(db, entry_type="manual_note")
    assert repo.update_note(note.id, uid=8, title="stolen") is None
    assert repo.update_note(note.id, uid=7, title="更新判断").title == "更新判断"
    investment_report = report(db)
    assert repo.update_note(investment_report.id, uid=7, title="bad") is None
    assert not repo.delete_note(investment_report.id, uid=7)
    assert not repo.delete_note(note.id, uid=8)
    assert repo.delete_note(note.id, uid=7)


def test_news_upsert_updates_structure_without_duplicate_or_report(db):
    seed_news(db)
    NewsAnalysisRepo(db).persist_premarket(
        [dict(news_id_or_url="https://example.com/news", importance_score=7, related_symbols=["AMD"])],
        [],
        model="new-model",
        analyzed_at=NOW,
    )
    with db.get_session() as session:
        analysis = session.scalars(select(NewsAnalysis)).one()
        assert analysis.importance_score == 7
        assert analysis.related_symbols == ["AMD"]
        assert analysis.model == "new-model"
        assert session.scalar(select(func.count()).select_from(TimelineEntry)) == 0


def test_three_sources_filters_sort_pagination_and_summary(db):
    report(db)
    report(db, entry_type="manual_note", market="CN", importance="normal", actionability="none")
    report(db, uid=8, title="private")
    seed_news(db, score=9)
    seed_news(db, score=10, url="https://example.com/top")
    db._run_write_transaction(
        "seed",
        lambda session: session.add(
            FinanceEvent(
                provider="test",
                event_key="cpi",
                calendar_type="macro",
                market="US",
                event_date=NOW.date(),
                event_datetime=NOW,
                title="CPI",
                content="通胀数据",
            )
        ),
    )
    service = TimelineService(db)
    result = service.list(**QUERY)
    assert result["total"] == 5
    assert {item.category for item in result["items"]} == {"event", "news", "analysis", "note"}
    news = service.list(**QUERY, category="news")["items"]
    assert [item.importance_score for item in news] == [10, 9]
    assert news[1].detail_payload["watch_points"] == ["订单"]
    assert news[1].event_time == NOW
    assert service.list(**QUERY, market="CN")["total"] == 1
    assert service.list(**QUERY, importance="high", actionability="consider")["total"] == 1
    first = service.list(**QUERY, limit=2)
    second = service.list(**QUERY, cursor=TimelineCursor.decode(first["next_cursor"]), limit=2)
    assert second["items"][0].id == result["items"][2].id
    summary = service.summary(**QUERY)[0]
    assert summary.model_dump() == dict(
        date="2026-09-06", total=5, critical=3, high=1, event_count=1, news_count=2, analysis_count=1, note_count=1
    )


def test_news_usage_preserves_multiple_symbols_and_queries(db):
    from finance_analysis.search import SearchResponse, SearchResult

    manager = object.__new__(DatabaseManager)
    manager._run_write_transaction = db._run_write_transaction
    manager.get_session = db.get_session
    response = SearchResponse(
        query="chips",
        provider="test",
        success=True,
        results=[SearchResult(title="Chip demand", snippet="Growth", url="https://example.com/shared", source="test")],
    )
    for symbol, usage, query in [
        ("NVDA", "premarket_news", "q1"),
        ("AMD", "intraday_news", "q2"),
        ("AMD", "intraday_news", "q2"),
    ]:
        manager.save_news_intel(code=symbol, usage_type=usage, response=response, query_context={"query_id": query})
    with db.get_session() as session:
        assert session.scalar(select(func.count()).select_from(NewsIntel)) == 1
        assert session.scalar(select(func.count()).select_from(NewsIntelUsage)) == 2
    assert len(manager.get_recent_news("NVDA")) == len(manager.get_recent_news("AMD")) == 1
    assert len(manager.get_news_intel_by_query_id("q1")) == len(manager.get_news_intel_by_query_id("q2")) == 1
    assert "dimension" not in NewsIntel.__table__.columns


def test_api_filters_summary_note_crud_and_validation(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from finance_analysis.interfaces.api.v1.endpoints import timeline
    from finance_analysis.interfaces.api.v1.router import router

    assert not any(route.path.startswith("/api/v1/calendar") for route in router.routes)
    monkeypatch.setattr(timeline, "TimelineService", lambda: TimelineService(db))
    monkeypatch.setattr(timeline, "TimelineEntryRepo", lambda: TimelineEntryRepo(db))
    monkeypatch.setattr(timeline, "get_effective_uid", lambda request: 7)
    app = FastAPI()
    from finance_analysis.interfaces.api.middlewares.error_handler import add_error_handlers
    add_error_handlers(app)
    app.include_router(timeline.router, prefix="/api/v1/timeline")
    client = TestClient(app)
    report(db)
    seed_news(db)
    path = "/api/v1/timeline"
    response = client.get(
        path, params=dict(date="2026-09-06", market="US", category="news", importance="critical", actionability="watch")
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["detail_payload"]["impact_reason"] == "需求上升"
    assert client.get(path + "/summary", params={"date": "2026-09-06"}).json()[0]["total"] == 2
    for params in (
        {"timezone": "bad"},
        {"category": "a_share"},
        {"date": "2026-09-06", "start_date": "2026-09-01"},
        {"start_date": "2026-09-06", "end_date": "2026-09-05"},
        {"cursor": "abc"},
        {"importance": "bad"},
    ):
        assert client.get(path, params=params).status_code == 422
    payload = dict(event_time=NOW.isoformat(), title="笔记", summary="等待", content="细节")
    response = client.post(path + "/notes", json=payload)
    assert response.status_code == 201
    note_id = response.json()["id"]
    assert client.put(f"{path}/notes/{note_id}", json=payload | {"title": "更新"}).status_code == 200
    assert client.delete(f"{path}/notes/{note_id}").status_code == 204
    assert client.delete(f"{path}/notes/{note_id}").status_code == 404
    assert client.post(path + "/notes", json=payload | {"event_time": "2026-09-06T08:00:00"}).status_code == 422


@pytest.mark.parametrize(
    "market,entry_type,module_name,reporter_name",
    [
        ("CN", "a_share_pre_close", "a_share_pre_close_review", "ASharePreCloseReporter"),
        ("US", "us_postmarket", "us_postmarket_review", "USPostmarketReviewReporter"),
    ],
)
def test_reporters_persist_business_types_and_full_report(
    db, monkeypatch, market, entry_type, module_name, reporter_name
):
    import importlib

    module = importlib.import_module(f"finance_analysis.tasks.celery.jobs.{module_name}.reporter")
    monkeypatch.setattr(module, "get_current_task_id", lambda: "report-run")
    summary = SimpleNamespace(
        finished_at=NOW,
        trading_date=NOW.date(),
        market_state="谨慎",
        risk_state="high",
        turnover_state="下降",
        market_regime="neutral",
        report="# Full report",
    )
    if market == "CN":
        monkeypatch.setattr(module, "render_report", lambda summary: "# Full report")
    reporter = getattr(module, reporter_name)(
        timeline_repo=TimelineEntryRepo(db), user_repo=SimpleNamespace(ensure_default_admin=lambda: 7)
    )
    entry_id = reporter.record_report(summary)
    with db.get_session() as session:
        row = session.get(TimelineEntry, entry_id)
        assert row.source_run_id == "report-run"
        assert row.entry_type == entry_type
        assert row.market == market
        assert row.content == "# Full report"
        assert row.summary and not row.summary.startswith("#")
        assert row.importance == "high"


def test_us_premarket_pipeline_persists_report_and_returns_task_statistics(db, monkeypatch):
    from unittest.mock import MagicMock

    from finance_analysis.tasks.celery.jobs.us_premarket_analysis.service import USPremarketAnalysisTaskService

    pipeline = MagicMock()
    pipeline.run.return_value = [SimpleNamespace(code="NVDA")]
    pipeline._generate_aggregate_report.return_value = "# Full report"
    monkeypatch.setattr("finance_analysis.analysis.pipeline.StockAnalysisPipeline", lambda **kwargs: pipeline)
    monkeypatch.setattr("finance_analysis.analysis.pipeline_config.get_pipeline_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "finance_analysis.database.repositories.watch_list.get_watch_list_codes_by_market", lambda market: ["NVDA"]
    )
    monkeypatch.setattr(
        "finance_analysis.database.repositories.timeline.TimelineEntryRepo", lambda: TimelineEntryRepo(db)
    )
    monkeypatch.setattr(
        "finance_analysis.database.repositories.user.UserRepository",
        lambda: SimpleNamespace(ensure_default_admin=lambda: 7),
    )
    result = USPremarketAnalysisTaskService().run()
    assert result["success_count"] == 1
    with db.get_session() as session:
        row = session.scalars(select(TimelineEntry)).one()
        assert row.entry_type == "us_premarket"
        assert row.content == "# Full report"
        assert row.related_symbols == ["NVDA"]


def test_news_job_persists_each_selected_fact_analysis_only(db, monkeypatch):
    from unittest.mock import MagicMock

    from finance_analysis.integrations.market_data.providers.longbridge.news import LongbridgeNewsRecord
    from finance_analysis.search import SearchResponse, SearchResult
    from finance_analysis.tasks.celery.jobs.us_premarket_news.domain_service import USPremarketNewsService

    manager = object.__new__(DatabaseManager)
    manager._run_write_transaction = db._run_write_transaction
    manager.get_session = db.get_session
    fetcher = MagicMock()
    url = "https://example.com/news-job"

    def fetch(symbol, **kwargs):
        manager.save_news_intel(
            code=symbol,
            usage_type="premarket_news",
            response=SearchResponse(
                query="chips",
                provider="test",
                success=True,
                results=[
                    SearchResult(
                        title="Growth", snippet="Orders", url=url, source="test", published_date=NOW.isoformat()
                    )
                ],
            ),
            query_context={"query_id": kwargs["query_id"]},
        )
        return [LongbridgeNewsRecord(news_id="job", title="Growth", description="Orders", url=url, published_at=NOW)]

    fetcher.fetch_and_save_news.side_effect = fetch
    llm = MagicMock(model_used="actual-model")
    llm.select_important_news.return_value = [dict(news_id_or_url=url, importance_score=9)]
    llm.judge_impact.return_value = [
        dict(news_id_or_url=url, impact="bullish", impact_score=3, related_symbols=["AMD"])
    ]
    reporter = MagicMock()
    service = USPremarketNewsService(
        config=SimpleNamespace(),
        longbridge_fetcher=MagicMock(),
        news_fetcher=fetcher,
        llm_analyzer=llm,
        reporter=reporter,
        db=db,
    )
    monkeypatch.setattr(
        "finance_analysis.tasks.celery.jobs.us_premarket_news.domain_service.build_premarket_symbol_universe",
        lambda symbols: ["NVDA"],
    )
    summary = service.run(["NVDA"], now=NOW)
    assert summary.inserted_news_count == 1
    reporter.send_notification.assert_called_once()
    with db.get_session() as session:
        analysis = session.scalars(select(NewsAnalysis)).one()
        assert analysis.model == "actual-model"
        assert analysis.related_symbols == ["NVDA", "AMD"]
        assert analysis.impact_score == 3
        assert session.scalar(select(func.count()).select_from(TimelineEntry)) == 0


@pytest.mark.parametrize(
    "published_days,observed_days,expected", [(0, 0, True), (None, 0, True), (30, 0, False), (None, 8, False)]
)
def test_recent_news_publication_first_and_relevant_observation(
    db, monkeypatch, published_days, observed_days, expected
):
    from datetime import timedelta

    monkeypatch.setattr("finance_analysis.database.session.utc_now", lambda: NOW)

    def seed(session):
        news = NewsIntel(
            title="time",
            url="https://example.com/time",
            fetched_at=NOW - timedelta(days=8),
            published_date=None if published_days is None else NOW - timedelta(days=published_days),
        )
        session.add(news)
        session.flush()
        session.add_all(
            [
                NewsIntelUsage(
                    news_intel_id=news.id,
                    symbol="NVDA",
                    usage_type="premarket_news",
                    query_id="q",
                    observed_at=NOW - timedelta(days=observed_days),
                ),
                NewsIntelUsage(
                    news_intel_id=news.id, symbol="AMD", usage_type="intraday_news", query_id="other", observed_at=NOW
                ),
            ]
        )

    db._run_write_transaction("seed", seed)
    assert bool(DatabaseManager.get_recent_news(db, "NVDA", days=1)) is expected


@pytest.mark.parametrize("published", [True, False])
def test_timeline_news_publication_or_analysis_time(db, published):
    from datetime import timedelta

    seed_news(db)
    with db.get_session() as session, session.begin():
        fact = session.scalars(select(NewsIntel)).one()
        fact.fetched_at = NOW - timedelta(days=8)
        fact.published_date = NOW - timedelta(hours=1) if published else None
    item = TimelineService(db).list(**QUERY, category="news")["items"][0]
    assert item.event_time == (NOW - timedelta(hours=1) if published else NOW)


def test_feed_chronology_overrides_importance_and_pagination_is_stable(db):
    from datetime import timedelta

    report(db, event_time=NOW - timedelta(hours=1), importance="critical", title="older critical")
    report(db, event_time=NOW, importance="normal", title="newer normal")
    report(db, event_time=NOW, importance="low", title="newer low")
    service = TimelineService(db)
    items = service.list(**QUERY)["items"]
    assert [item.title for item in items] == ["newer low", "newer normal", "older critical"]
    loaded = []
    cursor = None
    while True:
        result = service.list(**QUERY, cursor=cursor, limit=1)
        loaded.extend(item.id for item in result["items"])
        if not result["has_more"]:
            assert result["next_cursor"] is None
            break
        cursor = TimelineCursor.decode(result["next_cursor"])
    assert loaded == [item.id for item in items]


def test_api_default_range_excludes_future_and_summary_agrees(db, monkeypatch):
    from datetime import timedelta
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from finance_analysis.interfaces.api.v1.endpoints import timeline

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(timeline, "datetime", FixedDatetime)
    monkeypatch.setattr(timeline, "get_effective_uid", lambda request: 7)
    monkeypatch.setattr(timeline, "TimelineService", lambda: TimelineService(db))
    report(db, title="today")
    report(db, title="future", event_time=NOW + timedelta(days=1))
    report(db, title="outside", event_time=NOW - timedelta(days=8))
    app = FastAPI()
    app.include_router(timeline.router, prefix="/timeline")
    client = TestClient(app)
    items = client.get("/timeline").json()["items"]
    assert [item["title"] for item in items] == ["today"]
    assert sum(day["total"] for day in client.get("/timeline/summary").json()) == 1
    assert client.get("/timeline?date=2026-09-07").json()["items"][0]["title"] == "future"


def test_premarket_freshness_and_history_use_only_relevant_usage(db):
    from datetime import timedelta
    from finance_analysis.tasks.celery.jobs.us_premarket_news.domain_service import USPremarketNewsService

    def seed(session):
        for title, published, observed in [
            ("published today", NOW, NOW),
            ("unpublished observed today", None, NOW),
            ("old publication", NOW - timedelta(days=30), NOW),
            ("unrelated observation", None, NOW - timedelta(days=8)),
        ]:
            fact = NewsIntel(
                title=title,
                url="https://example.com/" + title,
                published_date=published,
                fetched_at=NOW - timedelta(days=8),
            )
            session.add(fact)
            session.flush()
            session.add_all(
                [
                    NewsIntelUsage(
                        news_intel_id=fact.id,
                        symbol="NVDA",
                        query_id="q",
                        usage_type="premarket_news",
                        observed_at=observed,
                    ),
                    NewsIntelUsage(
                        news_intel_id=fact.id,
                        symbol="AMD",
                        query_id="other",
                        usage_type="intraday_news",
                        observed_at=NOW + timedelta(hours=1),
                    ),
                ]
            )

    db._run_write_transaction("seed", seed)
    service = USPremarketNewsService.__new__(USPremarketNewsService)
    service.db = db
    assert {item.title for item in service._load_candidate_news(NOW, {})} == {
        "published today",
        "unpublished observed today",
    }
    history = DatabaseManager.get_news_intel_by_query_id(db, "q")
    assert [item.title for item in history] == [
        "unpublished observed today",
        "published today",
        "unrelated observation",
        "old publication",
    ]


@pytest.mark.parametrize("mutation", ["none", "insert", "delete"])
def test_cursor_continues_after_loaded_position_despite_feed_changes(db, mutation):
    from datetime import timedelta
    from sqlalchemy import delete

    for index, title in enumerate("ABCD"):
        report(db, title=title, event_time=NOW - timedelta(hours=index))
    service = TimelineService(db)
    first = service.list(**QUERY, limit=2)
    assert [item.title for item in first["items"]] == ["A", "B"]
    assert first["has_more"] is True
    if mutation == "insert":
        report(db, title="X", event_time=NOW + timedelta(minutes=5))
    elif mutation == "delete":
        db._run_write_transaction(
            "delete", lambda session: session.execute(delete(TimelineEntry).where(TimelineEntry.title.in_(["A", "B"])))
        )
    second = service.list(**QUERY, limit=2, cursor=TimelineCursor.decode(first["next_cursor"]))
    assert [item.title for item in second["items"]] == ["C", "D"]
    assert second["has_more"] is False
    assert second["next_cursor"] is None
    assert second["total"] == {"none": 4, "insert": 5, "delete": 2}[mutation]


def test_cursor_ties_across_all_sources(db):
    report(db)
    report(db, entry_type="manual_note")
    seed_news(db)
    seed_news(db, url="https://example.com/second")
    db._run_write_transaction(
        "seed",
        lambda session: session.add(
            FinanceEvent(
                provider="test",
                event_key="ties",
                calendar_type="macro",
                market="US",
                event_date=NOW.date(),
                event_datetime=NOW,
                title="CPI",
                content="test",
            )
        ),
    )
    service = TimelineService(db)
    expected = service.list(**QUERY)["items"]
    assert [item.source_type for item in expected] == ["finance_event", "news", "news", "note", "report"]
    assert expected[1].source_id > expected[2].source_id
    loaded = []
    cursor = None
    while True:
        batch = service.list(**QUERY, cursor=cursor, limit=1)
        loaded.extend(item.id for item in batch["items"])
        if not batch["has_more"]:
            assert batch["next_cursor"] is None
            break
        cursor = TimelineCursor.decode(batch["next_cursor"])
    assert loaded == [item.id for item in expected]
    last = expected[-1]
    empty = service.list(**QUERY, cursor=TimelineCursor(last.event_time, last.source_type, last.source_id))
    assert empty["items"] == []
    assert empty["has_more"] is False
    assert empty["next_cursor"] is None


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"event_time": "bad", "source_type": "news", "source_id": 1},
        {"event_time": "2026-09-06T08:00:00", "source_type": "news", "source_id": 1},
        {"event_time": NOW.isoformat(), "source_type": "bad", "source_id": 1},
        {"event_time": NOW.isoformat(), "source_type": "news", "source_id": True},
        {"event_time": NOW.isoformat(), "source_type": "news", "source_id": "1"},
        {"event_time": NOW.isoformat(), "source_type": "news", "source_id": -1},
        {"event_time": NOW.isoformat(), "source_type": "news", "source_id": 2**63},
        {"event_time": "0001-01-01T00:00:00+14:00", "source_type": "news", "source_id": 1},
    ],
)
def test_invalid_cursor_payload_returns_422_before_query(monkeypatch, payload):
    import base64
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from finance_analysis.interfaces.api.v1.endpoints import timeline

    monkeypatch.setattr(timeline, "get_effective_uid", lambda request: 7)

    def unexpected_query():
        raise AssertionError("Invalid cursor must not query the database")

    monkeypatch.setattr(timeline, "TimelineService", unexpected_query)
    app = FastAPI()
    app.include_router(timeline.router, prefix="/timeline")
    client = TestClient(app)
    token = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    assert client.get("/timeline", params={"cursor": token}).status_code == 422
    for malformed in ("abc", "", "not+url/base64", "x" * 1025):
        assert client.get("/timeline", params={"cursor": malformed}).status_code == 422


def test_cursor_api_contract_and_round_trip(db, monkeypatch):
    from datetime import timedelta
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from finance_analysis.interfaces.api.v1.endpoints import timeline

    monkeypatch.setattr(timeline, "get_effective_uid", lambda request: 7)
    monkeypatch.setattr(timeline, "TimelineService", lambda: TimelineService(db))
    app = FastAPI()
    app.include_router(timeline.router, prefix="/timeline")
    client = TestClient(app)
    report(db, title="newer", event_time=NOW + timedelta(microseconds=1))
    report(db, title="older")
    first = client.get("/timeline", params={"date": "2026-09-06", "limit": 1}).json()
    assert set(first) == {"items", "total", "limit", "next_cursor", "has_more"}
    assert first["has_more"] is True
    position = TimelineCursor.decode(first["next_cursor"])
    assert position.event_time == NOW + timedelta(microseconds=1)
    second = client.get("/timeline", params={"date": "2026-09-06", "limit": 1, "cursor": first["next_cursor"]}).json()
    assert second["items"][0]["title"] == "older"
    assert second["has_more"] is False
    assert second["next_cursor"] is None
