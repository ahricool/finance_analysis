"""Public investment timeline contracts and persistence boundaries (offline)."""

import re
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
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
from finance_analysis.database.session import DatabaseManager
from finance_analysis.timeline.cursor import TimelineCursor
from finance_analysis.timeline.service import TimelineService  # pragma: allowlist secret

NOW = datetime(2026, 9, 6, 8, tzinfo=timezone.utc)
QUERY = dict(timezone_name="Asia/Shanghai")
TIMELINE_ROOT = Path(__file__).resolve().parents[1] / "src/finance_analysis"  # pragma: allowlist secret


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


def calendar_marker(db, **overrides):
    from uuid import uuid4
    values = dict(event_key=uuid4().hex, calendar_type="earnings", symbol="NVDA.US", title="财报事件")
    for key in ("title", "market"):
        if key in overrides:
            values[key] = overrides[key]
    values["event_datetime"] = overrides.get("event_time", NOW)
    return event(db, **values)


def event(db, **overrides):
    values = dict(
        provider="yfinance",
        event_key="cpi",
        calendar_type="macro",
        market="US",
        event_date=NOW.date(),
        event_datetime=NOW,
        title="CPI",
        content="通胀数据",
    )
    values |= overrides

    def write(session):
        row = FinanceEvent(**values)
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    return db._run_write_transaction("seed", write)


def seed_news(db, score=9, url="https://example.com/news", published=NOW):
    db._run_write_transaction(
        "seed",
        lambda session: session.add(
            NewsIntel(title="芯片需求", snippet="订单增长", url=url, published_date=published, fetched_at=NOW)
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
    assert not (TIMELINE_ROOT / "database/repositories/calendar.py").exists()
    for job in ("a_share_intraday_analysis", "us_intraday_analysis"):
        source = "\n".join(p.read_text() for p in (TIMELINE_ROOT / "tasks/celery/jobs" / job).glob("*.py"))
        for forbidden in (
            "CalendarRepo",
            "calendar_id",
            "record_summary",
            "record_signal",
            "TimelineEntry",
            "NewsAnalysis",
        ):
            assert forbidden not in source


def test_timeline_domain_has_no_uid_or_note_left():
    assert "uid" not in TimelineEntry.__table__.columns
    assert not (TIMELINE_ROOT / "interfaces/api/v1/schemas/timeline.py").exists()
    sources = [
        TIMELINE_ROOT / "database/models/timeline.py",
        TIMELINE_ROOT / "interfaces/api/v1/endpoints/timeline.py",
        *sorted((TIMELINE_ROOT / "timeline").glob("*.py")),
    ]
    for path in sources:
        text = path.read_text()
        for forbidden in (r"\buid\b", "manual_note", "NoteInput", r"\bnotes?\b", "get_effective_uid"):
            assert not re.search(forbidden, text), f"{path.name} still mentions {forbidden}"
    for job in ("a_share_pre_close_review/reporter.py", "us_postmarket_review/reporter.py"):
        text = (TIMELINE_ROOT / "tasks/celery/jobs" / job).read_text()
        assert "ensure_default_admin" not in text and "UserRepository" not in text
    premarket = (TIMELINE_ROOT / "tasks/celery/jobs/us_premarket_analysis/service.py").read_text()
    assert "ensure_default_admin" not in premarket and "UserRepository" not in premarket


def test_manual_note_entry_type_is_rejected_by_the_database(db):
    from sqlalchemy import text as sql_text

    with db.get_session() as session:
        session.execute(sql_text("PRAGMA legacy_alter_table=OFF"))
    with pytest.raises(Exception):
        db._run_write_transaction(
            "note",
            lambda session: session.execute(
                sql_text(
                    "INSERT INTO timeline_entries "
                    "(entry_type, event_time, title, summary, content, importance, actionability, related_symbols) "
                    "VALUES ('manual_note', '2026-09-06 08:00:00', 't', 's', 'c', 'normal', 'none', '[]')"
                )
            ),
        )


def test_note_routes_are_gone():
    from finance_analysis.interfaces.api.v1.endpoints import timeline  # pragma: allowlist secret

    paths = {(route.path, tuple(sorted(route.methods))) for route in timeline.router.routes}
    assert paths == {("", ("GET",))}


def test_news_upsert_updates_structure_without_duplicate_or_calendar_marker(db):
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


def test_three_sources_filters_and_pagination(db):
    calendar_marker(db)
    calendar_marker(db, market="CN", importance="normal", actionability="none", entry_type="a_share_pre_close")
    seed_news(db, score=9)
    seed_news(db, score=10, url="https://example.com/top")
    event(db)
    service = TimelineService(db)
    result = service.list(**QUERY)
    assert result["total"] == 5
    assert {item.category for item in result["items"]} == {"event", "news"}
    news = service.list(**QUERY, category="news")["items"]
    assert [item.importance_score for item in news] == [10, 9]
    assert news[1].detail_payload["watch_points"] == ["订单"]
    assert news[1].event_time == NOW
    assert service.list(**QUERY, market="CN")["total"] == 1
    first = service.list(**QUERY, limit=2)
    second = service.list(**QUERY, cursor=TimelineCursor.decode(first["next_cursor"]), limit=2)
    assert second["items"][0].id == result["items"][2].id


def test_calendar_type_filter_separates_earnings_and_macro(db):
    event(db, event_key="macro", calendar_type="macro", title="CPI")
    event(db, event_key="nvda", calendar_type="earnings", symbol="NVDA", title="NVDA Earnings")
    service = TimelineService(db)
    assert [item.title for item in service.list(**QUERY, category="event", calendar_type="earnings")["items"]] == [
        "NVDA Earnings"
    ]
    assert [item.title for item in service.list(**QUERY, category="event", calendar_type="macro")["items"]] == ["CPI"]
    assert service.list(**QUERY, category="event")["total"] == 2
    assert {item.calendar_type for item in service.list(**QUERY, category="event")["items"]} == {"earnings", "macro"}
    assert service.list(**QUERY, category="news")["items"] == []


def test_earnings_detail_exposes_typed_payload_and_source_providers(db):
    import json

    event(
        db,
        event_key="nvda-q3",
        calendar_type="earnings",
        market="US",
        symbol="NVDA",
        counter_name="NVIDIA",
        reporting_period="Q3",
        market_session="amc",
        eps_estimate=1.32,
        reported_eps=1.46,
        eps_surprise_pct=10.6,
        currency="USD",
        event_datetime=None,
        raw_payload_json=json.dumps({"yfinance": {}, "longbridge": {}}),
    )
    item = TimelineService(db).list(**QUERY, calendar_type="earnings")["items"][0]
    payload = item.detail_payload
    assert item.calendar_type == "earnings"
    assert payload["counter_name"] == "NVIDIA"
    assert payload["reporting_period"] == "Q3"
    assert payload["market_session"] == "amc"
    assert payload["eps_estimate"] == 1.32 and payload["reported_eps"] == 1.46
    assert payload["eps_surprise_pct"] == 10.6
    assert payload["all_day"] is True
    assert payload["source_providers"] == ["longbridge", "yfinance"]


def test_source_providers_fall_back_to_the_primary_provider(db):
    event(db, event_key="single", provider="yfinance", raw_payload_json=None)
    item = TimelineService(db).list(**QUERY)["items"][0]
    assert item.detail_payload["source_providers"] == ["yfinance"]


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


def timeline_client(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from finance_analysis.interfaces.api.middlewares.error_handler import add_error_handlers  # pragma: allowlist secret
    from finance_analysis.interfaces.api.v1.endpoints import timeline

    monkeypatch.setattr(timeline, "TimelineService", lambda: TimelineService(db))
    app = FastAPI()
    add_error_handlers(app)
    app.include_router(timeline.router, prefix="/api/v1/timeline")
    return TestClient(app)


def test_api_is_public_and_validates_input(db, monkeypatch):
    from finance_analysis.interfaces.api.v1.router import router  # pragma: allowlist secret

    assert not any(route.path.startswith("/api/v1/calendar") for route in router.routes)
    client = timeline_client(db, monkeypatch)
    calendar_marker(db)
    seed_news(db)
    path = "/api/v1/timeline"
    response = client.get(path, params=dict(market="US", category="news"))
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["detail_payload"]["impact_reason"] == "需求上升"
    for params in (
        {"timezone": "bad"},
        {"category": "note"},
        {"category": "a_share"},
        {"calendar_type": "bad"},
        {"importance": "bad"},
        {"cursor": "abc"},
        {"end_date": "not-a-date"},
    ):
        assert client.get(path, params=params).status_code == 422
    for removed in (
        client.post(path + "/notes", json={}),
        client.put(path + "/notes/1", json={}),
        client.delete(path + "/notes/1"),
        client.get(path + "/summary"),
    ):
        assert removed.status_code == 404


def test_api_serves_identical_content_regardless_of_session(db, monkeypatch):
    import inspect as inspect_module

    from finance_analysis.interfaces.api.v1.endpoints import timeline  # pragma: allowlist secret

    assert "request" not in inspect_module.signature(timeline.timeline_query).parameters
    client = timeline_client(db, monkeypatch)
    calendar_marker(db, title="公共事件")
    first = client.get("/api/v1/timeline").json()
    second = client.get("/api/v1/timeline", headers={"Cookie": "session=other-user"}).json()
    assert first == second
    assert [item["title"] for item in first["items"]] == ["公共事件"]


@pytest.mark.parametrize(
    "market,entry_type,module_name,reporter_name",
    [
        ("CN", "a_share_pre_close", "a_share_pre_close_review", "ASharePreCloseReporter"),
        ("US", "us_postmarket", "us_postmarket_review", "USPostmarketReviewReporter"),
    ],
)
def test_reporters_persist_public_reports_without_an_owner(
    db, monkeypatch, market, entry_type, module_name, reporter_name
):
    import importlib

    module = importlib.import_module(f"finance_analysis.tasks.celery.jobs.{module_name}.reporter")
    from unittest.mock import Mock
    summary = SimpleNamespace(trading_date=NOW.date(), risk_state="high", report="# Full report", warnings=[])
    if market == "CN":
        monkeypatch.setattr(module, "render_report", lambda summary: "# Full report")
    notifier = Mock()
    reporter = getattr(module, reporter_name)(notifier=notifier)
    reporter.send_notification(summary, send_notification=False)
    notifier.send.assert_called_once()
    assert notifier.send.call_args.args[0] == "# Full report"
    assert notifier.send.call_args.kwargs["push"] is False
    with db.get_session() as session:
        assert session.scalar(select(func.count()).select_from(TimelineEntry)) == 0


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
    result = USPremarketAnalysisTaskService().run()
    assert result["success_count"] == 1
    pipeline.run.assert_called_once()
    with db.get_session() as session:
        assert session.scalar(select(func.count()).select_from(TimelineEntry)) == 0


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
    seed_news(db)
    with db.get_session() as session, session.begin():
        fact = session.scalars(select(NewsIntel)).one()
        fact.fetched_at = NOW - timedelta(days=8)
        fact.published_date = NOW - timedelta(hours=1) if published else None
    item = TimelineService(db).list(**QUERY, category="news")["items"][0]
    assert item.event_time == (NOW - timedelta(hours=1) if published else NOW)


def test_feed_chronology_overrides_importance_and_pagination_is_stable(db):
    calendar_marker(db, event_time=NOW - timedelta(hours=1), importance="critical", title="older critical")
    calendar_marker(db, event_time=NOW, importance="normal", title="newer normal")
    calendar_marker(db, event_time=NOW, importance="low", title="newer low")
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


def seed_desc_fixture(db):
    event(db, event_key="nvda", calendar_type="earnings", symbol="NVDA", title="NVDA Earnings",
          event_datetime=datetime(2026, 10, 1, 20, tzinfo=timezone.utc))
    event(db, event_key="fomc", calendar_type="macro", title="FOMC",
          event_datetime=datetime(2026, 9, 20, 12, tzinfo=timezone.utc))
    seed_news(db, url="https://example.com/desc-news", published=datetime(2026, 9, 10, 12, tzinfo=timezone.utc))
    calendar_marker(db, title="Analysis", event_time=datetime(2026, 9, 9, 12, tzinfo=timezone.utc))


@pytest.mark.parametrize(
    "filters,expected",
    [
        ({}, ["NVDA Earnings", "FOMC", "芯片需求", "Analysis"]),
        ({"category": "event", "calendar_type": "earnings"}, ["NVDA Earnings", "Analysis"]),
        ({"category": "event", "calendar_type": "macro"}, ["FOMC"]),
        ({"category": "news"}, ["芯片需求"]),
        ({"category": "analysis"}, []),
    ],
)
def test_every_tab_orders_future_and_past_events_newest_first(db, filters, expected):
    seed_desc_fixture(db)
    items = TimelineService(db).list(**QUERY, **filters)["items"]
    assert [item.title for item in items] == expected


def test_cutoff_hides_later_events_and_keeps_desc_order(db):
    seed_desc_fixture(db)
    items = TimelineService(db).list(**QUERY, end_date=date(2026, 9, 20))["items"]
    assert [item.title for item in items] == ["FOMC", "芯片需求", "Analysis"]


def test_no_cutoff_keeps_future_messages(db):
    seed_desc_fixture(db)
    assert TimelineService(db).list(**QUERY)["total"] == 4


@pytest.mark.parametrize("timezone_name,visible", [("Asia/Shanghai", False), ("America/New_York", True)])
def test_cutoff_uses_the_display_timezone_end_of_day(db, timezone_name, visible):
    # 2026-09-20 18:00Z is already 2026-09-21 02:00 in Shanghai but still 2026-09-20 14:00 in New York.
    event(db, event_key="boundary", title="边界事件", event_datetime=datetime(2026, 9, 20, 18, tzinfo=timezone.utc))
    items = TimelineService(db).list(timezone_name=timezone_name, end_date=date(2026, 9, 20))["items"]
    assert [item.title for item in items] == (["边界事件"] if visible else [])


def test_cutoff_and_cursor_paginate_without_gaps_or_duplicates(db):
    seed_desc_fixture(db)
    service = TimelineService(db)
    cutoff = dict(end_date=date(2026, 9, 20))
    first = service.list(**QUERY, **cutoff, limit=2)
    assert [item.title for item in first["items"]] == ["FOMC", "芯片需求"]
    assert first["has_more"] is True
    second = service.list(**QUERY, **cutoff, limit=2, cursor=TimelineCursor.decode(first["next_cursor"]))
    assert [item.title for item in second["items"]] == ["Analysis"]
    assert second["has_more"] is False and second["next_cursor"] is None


def test_api_returns_all_future_messages_without_a_cutoff(db, monkeypatch):
    client = timeline_client(db, monkeypatch)
    calendar_marker(db, title="today")
    calendar_marker(db, title="future", event_time=NOW + timedelta(days=40))
    calendar_marker(db, title="past", event_time=NOW - timedelta(days=400))
    assert [item["title"] for item in client.get("/api/v1/timeline").json()["items"]] == ["future", "today", "past"]
    cutoff = client.get("/api/v1/timeline", params={"end_date": "2026-09-06"}).json()
    assert [item["title"] for item in cutoff["items"]] == ["today", "past"]


def test_premarket_freshness_and_history_use_only_relevant_usage(db):
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
    from sqlalchemy import delete

    for index, title in enumerate("ABCD"):
        calendar_marker(db, title=title, event_time=NOW - timedelta(hours=index))
    service = TimelineService(db)
    first = service.list(**QUERY, limit=2)
    assert [item.title for item in first["items"]] == ["A", "B"]
    assert first["has_more"] is True
    if mutation == "insert":
        calendar_marker(db, title="X", event_time=NOW + timedelta(minutes=5))
    elif mutation == "delete":
        db._run_write_transaction(
            "delete", lambda session: session.execute(delete(FinanceEvent).where(FinanceEvent.title.in_(["A", "B"])))
        )
    second = service.list(**QUERY, limit=2, cursor=TimelineCursor.decode(first["next_cursor"]))
    assert [item.title for item in second["items"]] == ["C", "D"]
    assert second["has_more"] is False
    assert second["next_cursor"] is None
    assert second["total"] == {"none": 4, "insert": 5, "delete": 2}[mutation]


def test_cursor_ties_across_all_sources(db):
    calendar_marker(db)
    calendar_marker(db, entry_type="a_share_pre_close")
    seed_news(db)
    seed_news(db, url="https://example.com/second")
    event(db, event_key="ties")
    service = TimelineService(db)
    expected = service.list(**QUERY)["items"]
    assert [item.source_type for item in expected] == ["finance_event", "finance_event", "finance_event", "news", "news"]
    assert expected[3].source_id > expected[4].source_id
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
        {"event_time": NOW.isoformat(), "source_type": "note", "source_id": 1},
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

    from finance_analysis.interfaces.api.v1.endpoints import timeline  # pragma: allowlist secret

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
    client = timeline_client(db, monkeypatch)
    calendar_marker(db, title="newer", event_time=NOW + timedelta(microseconds=1))
    calendar_marker(db, title="older")
    first = client.get("/api/v1/timeline", params={"limit": 1}).json()
    assert set(first) == {"items", "total", "limit", "next_cursor", "has_more"}
    assert first["has_more"] is True
    position = TimelineCursor.decode(first["next_cursor"])
    assert position.event_time == NOW + timedelta(microseconds=1)
    second = client.get("/api/v1/timeline", params={"limit": 1, "cursor": first["next_cursor"]}).json()
    assert second["items"][0]["title"] == "older"
    assert second["has_more"] is False
    assert second["next_cursor"] is None


@pytest.mark.parametrize("importance", ["critical", "high", "normal", "low"])
def test_importance_filters_unified_sources_and_cursor(db, monkeypatch, importance):
    for index, level in enumerate(("critical", "high", "normal", "low")):
        seed_news(db, score={"critical": 10, "high": 7, "normal": 5, "low": 1}[level],
                  url=f"https://example.com/{level}", published=NOW - timedelta(minutes=index))
        with db.get_session() as session, session.begin():
            row = session.scalar(select(NewsIntel).where(NewsIntel.url == f"https://example.com/{level}"))
            row.title = level
            analysis = session.scalar(select(NewsAnalysis).where(NewsAnalysis.news_intel_id == row.id))
            analysis.importance = level
    event(db)
    seed_news(db)
    client = timeline_client(db, monkeypatch)
    params = dict(importance=importance, market="US", end_date=NOW.date().isoformat(), limit=1)
    titles = []
    while True:
        response = client.get("/api/v1/timeline", params=params)
        assert response.status_code == 200
        page = response.json()
        assert all(item["importance"] == importance for item in page["items"])
        titles.extend(item["title"] for item in page["items"])
        if not page["has_more"]:
            break
        params["cursor"] = page["next_cursor"]
    assert importance in titles
    assert len(titles) == (3 if importance == "critical" else 1)


def test_importance_combines_with_calendar_type_market_and_cutoff(db, monkeypatch):
    event(db, event_key="match", title="earnings", calendar_type="earnings", symbol="NVDA", importance_score=9)
    event(db, event_key="later", title="later", calendar_type="earnings", symbol="NVDA", importance_score=9,
          event_datetime=NOW + timedelta(days=1))
    event(db, event_key="normal", title="normal", calendar_type="earnings", symbol="NVDA", importance_score=1)
    event(db, event_key="macro", title="CPI")
    event(db, event_key="cn", title="CN", calendar_type="earnings", symbol="NVDA", market="CN", importance_score=9)
    seed_news(db)
    calendar_marker(db, importance="critical")
    response = timeline_client(db, monkeypatch).get("/api/v1/timeline", params=dict(
        market="US", category="event", calendar_type="earnings", importance="critical", end_date="2026-09-06",
    ))
    assert response.status_code == 200
    assert [item["title"] for item in response.json()["items"]] == ["earnings"]


def test_legacy_reports_never_appear_in_timeline(db):
    db._run_write_transaction("seed-legacy", lambda session: session.add(TimelineEntry(
        entry_type="us_premarket", event_time=NOW, title="Legacy report", summary="old", content="old",
    )))
    event(db)
    result = TimelineService(db).list(**QUERY)
    assert result["total"] == 1
    assert result["items"][0].source_type == "finance_event"
