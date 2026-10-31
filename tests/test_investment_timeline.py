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
from finance_analysis.database.models.timeline import TimelineEntry
from finance_analysis.database.models.earnings_outlook import EarningsOutlookState
from finance_analysis.timeline.cursor import TimelineCursor
from finance_analysis.timeline.service import TimelineService  # pragma: allowlist secret

NOW = datetime(2026, 9, 6, 8, tzinfo=timezone.utc)
QUERY = dict(timezone_name="Asia/Shanghai")
TIMELINE_ROOT = Path(__file__).resolve().parents[1] / "src/finance_analysis"  # pragma: allowlist secret


class TestDB:
    __test__ = False

    def __init__(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        for model in (TimelineEntry, FinanceEvent, EarningsOutlookState):
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


def test_deleted_calendar_model_and_intraday_persistence():
    assert "calendar" not in Base.metadata.tables
    import finance_analysis.database.models as models

    assert not hasattr(models, "CalendarEntry")
    assert not (TIMELINE_ROOT / "database/repositories/calendar.py").exists()
    for job in ("a_share_intraday_analysis", "us_intraday_analysis"):
        assert not (TIMELINE_ROOT / "tasks/celery/jobs" / job).exists()


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
    for job in ("us_postmarket_review/reporter.py",):
        text = (TIMELINE_ROOT / "tasks/celery/jobs" / job).read_text()
        assert "ensure_default_admin" not in text and "UserRepository" not in text


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
    assert paths == {
        ("", ("GET",)),
        ("/earnings/{event_id}/outlook", ("GET",)),
        ("/earnings/{event_id}/outlook/refresh", ("POST",)),
    }


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
    path = "/api/v1/timeline"
    response = client.get(path, params=dict(market="US", category="event"))
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["calendar_type"] == "earnings"
    for params in (
        {"timezone": "bad"},
        {"category": "note"},
        {"category": "news"},
        {"category": "analysis"},
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
        monkeypatch.setattr(module, "render_notification", lambda summary: "Short push")
    notifier = Mock()
    reporter = getattr(module, reporter_name)(notifier=notifier)
    reporter.send_notification(summary, send_notification=False)
    notifier.send.assert_called_once()
    assert (
        notifier.send.call_args.kwargs["content"] if market == "CN" else notifier.send.call_args.args[0]
    ) == "# Full report"
    assert notifier.send.call_args.kwargs["push"] is False
    with db.get_session() as session:
        assert session.scalar(select(func.count()).select_from(TimelineEntry)) == 0


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
    event(
        db,
        event_key="nvda",
        calendar_type="earnings",
        symbol="NVDA",
        title="NVDA Earnings",
        event_datetime=datetime(2026, 10, 1, 20, tzinfo=timezone.utc),
    )
    event(
        db,
        event_key="fomc",
        calendar_type="macro",
        title="FOMC",
        event_datetime=datetime(2026, 9, 20, 12, tzinfo=timezone.utc),
    )
    calendar_marker(db, title="Analysis", event_time=datetime(2026, 9, 9, 12, tzinfo=timezone.utc))


@pytest.mark.parametrize(
    "filters,expected",
    [
        ({}, ["NVDA Earnings", "FOMC", "Analysis"]),
        ({"category": "event", "calendar_type": "earnings"}, ["NVDA Earnings", "Analysis"]),
        ({"category": "event", "calendar_type": "macro"}, ["FOMC"]),
    ],
)
def test_every_tab_orders_future_and_past_events_newest_first(db, filters, expected):
    seed_desc_fixture(db)
    items = TimelineService(db).list(**QUERY, **filters)["items"]
    assert [item.title for item in items] == expected


def test_cutoff_hides_later_events_and_keeps_desc_order(db):
    seed_desc_fixture(db)
    items = TimelineService(db).list(**QUERY, end_date=date(2026, 9, 20))["items"]
    assert [item.title for item in items] == ["FOMC", "Analysis"]


def test_no_cutoff_keeps_future_messages(db):
    seed_desc_fixture(db)
    assert TimelineService(db).list(**QUERY)["total"] == 3


@pytest.mark.parametrize("timezone_name,visible", [("Asia/Shanghai", False), ("America/New_York", True)])
def test_cutoff_uses_the_display_timezone_end_of_day(db, timezone_name, visible):
    # 2026-09-20 18:00Z is already 2026-09-21 02:00 in Shanghai but still 2026-09-20 14:00 in New York.
    event(db, event_key="boundary", title="边界事件", event_datetime=datetime(2026, 9, 20, 18, tzinfo=timezone.utc))
    items = TimelineService(db).list(timezone_name=timezone_name, end_date=date(2026, 9, 20))["items"]
    assert [item.title for item in items] == (["边界事件"] if visible else [])


def test_cutoff_and_cursor_paginate_without_gaps_or_duplicates(db):
    seed_desc_fixture(db)
    service = TimelineService(db)
    calendar_marker(db, title="earlier", event_time=datetime(2026, 9, 8, 12, tzinfo=timezone.utc))
    cutoff = dict(end_date=date(2026, 9, 20))
    first = service.list(**QUERY, **cutoff, limit=2)
    assert [item.title for item in first["items"]] == ["FOMC", "Analysis"]
    assert first["has_more"] is True
    second = service.list(**QUERY, **cutoff, limit=2, cursor=TimelineCursor.decode(first["next_cursor"]))
    assert [item.title for item in second["items"]] == ["earlier"]
    assert second["has_more"] is False and second["next_cursor"] is None


def test_api_returns_all_future_messages_without_a_cutoff(db, monkeypatch):
    client = timeline_client(db, monkeypatch)
    calendar_marker(db, title="today")
    calendar_marker(db, title="future", event_time=NOW + timedelta(days=40))
    calendar_marker(db, title="past", event_time=NOW - timedelta(days=400))
    assert [item["title"] for item in client.get("/api/v1/timeline").json()["items"]] == ["future", "today", "past"]
    cutoff = client.get("/api/v1/timeline", params={"end_date": "2026-09-06"}).json()
    assert [item["title"] for item in cutoff["items"]] == ["today", "past"]


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


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"event_time": "bad", "source_type": "finance_event", "source_id": 1},
        {"event_time": "2026-09-06T08:00:00", "source_type": "finance_event", "source_id": 1},
        {"event_time": NOW.isoformat(), "source_type": "bad", "source_id": 1},
        {"event_time": NOW.isoformat(), "source_type": "note", "source_id": 1},
        {"event_time": NOW.isoformat(), "source_type": "finance_event", "source_id": True},
        {"event_time": NOW.isoformat(), "source_type": "finance_event", "source_id": "1"},
        {"event_time": NOW.isoformat(), "source_type": "finance_event", "source_id": -1},
        {"event_time": NOW.isoformat(), "source_type": "finance_event", "source_id": 2**63},
        {"event_time": "0001-01-01T00:00:00+14:00", "source_type": "finance_event", "source_id": 1},
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


def test_importance_combines_with_calendar_type_market_and_cutoff(db, monkeypatch):
    event(db, event_key="match", title="earnings", calendar_type="earnings", symbol="NVDA", importance_score=9)
    event(
        db,
        event_key="later",
        title="later",
        calendar_type="earnings",
        symbol="NVDA",
        importance_score=9,
        event_datetime=NOW + timedelta(days=1),
    )
    event(db, event_key="normal", title="normal", calendar_type="earnings", symbol="NVDA", importance_score=1)
    event(db, event_key="macro", title="CPI")
    event(db, event_key="cn", title="CN", calendar_type="earnings", symbol="NVDA", market="CN", importance_score=9)
    calendar_marker(db, importance="critical")
    response = timeline_client(db, monkeypatch).get(
        "/api/v1/timeline",
        params=dict(
            market="US",
            category="event",
            calendar_type="earnings",
            importance="critical",
            end_date="2026-09-06",
        ),
    )
    assert response.status_code == 200
    assert [item["title"] for item in response.json()["items"]] == ["earnings"]


def test_legacy_reports_never_appear_in_timeline(db):
    db._run_write_transaction(
        "seed-legacy",
        lambda session: session.add(
            TimelineEntry(
                entry_type="us_premarket",
                event_time=NOW,
                title="Legacy report",
                summary="old",
                content="old",
            )
        ),
    )
    event(db)
    result = TimelineService(db).list(**QUERY)
    assert result["total"] == 1
    assert result["items"][0].source_type == "finance_event"
