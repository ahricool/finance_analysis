"""Offline end-to-end transactions with real SQL, fake market/LLM and deterministic locks."""

import json
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from finance_analysis.database.models import (
    FinanceEvent,
    Instrument,
    EarningsResearch,
    EarningsPrediction,
    EarningsOutlookState,
)
from finance_analysis.database.repositories.earnings_outlook import EarningsOutlookRepository, display_summary
from finance_analysis.earnings_outlook.service import EarningsOutlookService
from finance_analysis.llm.types import LLMResult
from .test_rules import context, raw

NOW = datetime(2026, 7, 1, 15, tzinfo=timezone.utc)


class DB:
    def __init__(self):
        self.engine = create_engine("sqlite://")
        self.writing = False
        for model in (Instrument, FinanceEvent, EarningsResearch, EarningsPrediction, EarningsOutlookState):
            model.__table__.create(self.engine)

    @contextmanager
    def get_session(self):
        with Session(self.engine, expire_on_commit=False) as session:
            yield session

    def _run_write_transaction(self, name, callback):
        with self.get_session() as session, session.begin():
            self.writing = True
            try:
                return callback(session)
            finally:
                self.writing = False


class Lock:
    held = set()

    def __init__(self, key):
        self.key = key
        self.acquired = False

    def acquire(self):
        self.acquired = self.key not in self.held
        if self.acquired:
            self.held.add(self.key)
        return self.acquired

    def release(self):
        if self.acquired:
            self.held.remove(self.key)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()


@pytest.fixture
def setup(monkeypatch):
    import finance_analysis.database.repositories.earnings_outlook as repo_module

    monkeypatch.setattr(repo_module, "utc_now", lambda: NOW)
    db = DB()
    repo = EarningsOutlookRepository(db)
    repo.lock = lambda event_id: Lock(("event", event_id))
    repo.slot = lambda slot: Lock(("slot", slot))
    with db.get_session() as s, s.begin():
        instrument = Instrument(
            id=1,
            code="A.US",
            name="A",
            market="US",
            native_code="A",
            instrument_type="STOCK",
            currency="USD",
            listing_status="ACTIVE",
            source="test",
        )
        s.add(instrument)
        s.add(
            FinanceEvent(
                id=1,
                provider="test",
                event_key="a",
                calendar_type="earnings",
                market="US",
                symbol="A.US",
                event_date=date(2026, 7, 2),
                reporting_period="2026-Q2",
                market_session="amc",
                title="A earnings",
                content="",
            )
        )
    resolver = NS(resolve_universe=lambda _: [instrument])
    member = dict(instrument_id=1, symbol="A.US", name="A", memberships=["us_sp500", "us_nasdaq100"])
    collector = Mock()

    def collect(e, m, now, window, public):
        assert not db.writing
        c = context()
        from finance_analysis.earnings_outlook.rules import schedule

        c.update(event=schedule(e), company=m, data_cutoff=now.isoformat())
        return c

    collector.collect.side_effect = collect
    llm = Mock()

    def complete(request, validator):
        assert not db.writing
        result = {"sources": [], "facts": [], "consensus": {}} if request.call_type == "earnings_research" else raw()
        text = json.dumps(result)
        validator(text)
        return LLMResult(text=text, backend="test", model="mock", search_evidence={"status": "unavailable"})

    llm.complete_text.side_effect = complete
    service = EarningsOutlookService(repo, llm, collector, resolver, clock=lambda: NOW)
    return service, db, repo, llm, {"A.US": member}


def test_cache_final_snapshot_and_failed_refresh_preserves_success(setup):
    service, db, repo, llm, members = setup
    assert service.refresh(1, "daily", members, {})["status"] == "success"
    old_id = repo.state(1).latest_prediction_id
    assert llm.complete_text.call_count == 2
    assert service.refresh(1, "daily", members, {})["status"] == "cached"
    assert llm.complete_text.call_count == 2
    # Different stage updates snapshot without forcing a new research call.
    assert service.refresh(1, "final", members, {})["status"] == "success"
    assert llm.complete_text.call_count == 3
    assert repo.state(1).latest_prediction_id != old_id
    latest = repo.state(1).latest_prediction_id
    llm.complete_text.side_effect = RuntimeError("upstream failed")
    with pytest.raises(RuntimeError):
        service.refresh(1, "manual", members, {})
    state = repo.state(1)
    assert state.status == "failed" and state.latest_prediction_id == latest and state.error
    with db.get_session() as s:
        assert s.scalar(select(func.count()).select_from(EarningsPrediction)) == 2


def test_event_lock_and_global_slots_never_call_llm_when_busy(setup):
    service, db, repo, llm, members = setup
    with repo.lock(1):
        assert service.refresh(1, "daily", members, {})["status"] == "busy"
    with repo.slot(0), repo.slot(1):
        assert service.refresh(1, "daily", members, {})["status"] == "busy"
    llm.complete_text.assert_not_called()


def test_freeze_and_changed_event_do_not_expose_old_target(setup):
    service, db, repo, llm, members = setup
    service.refresh(1, "daily", members, {})
    with db.get_session() as s, s.begin():
        row = s.get(FinanceEvent, 1)
        row.event_date = date(2026, 6, 30)
    assert service.refresh(1, "daily", members, {})["status"] == "frozen"
    summary = display_summary(repo.event(1), repo.state(1), members, NOW)
    assert summary["status"] == "superseded" and "target_trading_date" not in summary
    assert llm.complete_text.call_count == 2


def test_changed_consensus_invalidates_research_and_same_day_analysis(setup):
    service, db, repo, llm, members = setup
    service.refresh(1, "daily", members, {})
    with db.get_session() as s, s.begin():
        s.get(FinanceEvent, 1).eps_estimate = 2
    service.refresh(1, "daily", members, {})
    assert llm.complete_text.call_count == 4


def test_unverified_model_sources_are_not_used_as_live_evidence(setup):
    service, db, repo, llm, members = setup
    original = llm.complete_text.side_effect

    def call(request, validator):
        if request.call_type == "earnings_research":
            return LLMResult(
                text=json.dumps(
                    {
                        "sources": [
                            {"source_id": "fake", "url": "https://example.com", "published_at": NOW.isoformat()}
                        ],
                        "facts": [{"text": "claimed", "source_ids": ["fake"]}],
                        "conflicts": [{"source_ids": ["fake"], "description": "unverified claim"}],
                        "uncertainties": ["Unverified actual EPS"],
                    }
                ),
                backend="test",
                search_evidence={"status": "unverified"},
            )
        return original(request, validator)

    llm.complete_text.side_effect = call
    service.refresh(1, "daily", members, {})
    detail = repo.detail(1)
    assert detail["versions"][0]["research"]["facts"] == []
    assert detail["versions"][0]["research"]["conflicts"] == []
    assert detail["versions"][0]["research"]["uncertainties"] == []
    assert detail["versions"][0]["search_evidence"]["status"] == "unverified"


def test_report_arriving_during_model_call_cannot_create_prediction(setup):
    service, db, repo, llm, members = setup
    original = llm.complete_text.side_effect

    def call(request, validator):
        if request.call_type == "earnings_outlook":
            with db.get_session() as s, s.begin():
                s.get(FinanceEvent, 1).reported_eps = 1
        return original(request, validator)

    llm.complete_text.side_effect = call
    with pytest.raises(ValueError, match="reported"):
        service.refresh(1, "daily", members, {})
    assert repo.state(1).latest_prediction_id is None


def test_manual_refresh_hash_tracks_price_and_deduplicates_identical_input(setup):
    service, db, repo, llm, members = setup
    assert service.refresh(1, "manual", members, {})["status"] == "success"
    assert service.refresh(1, "manual", members, {})["status"] == "cached"
    original = service.collector.collect.side_effect

    def collect(*args):
        value = original(*args)
        value["reference_price"] = 101
        return value

    service.collector.collect.side_effect = collect
    assert service.refresh(1, "manual", members, {})["status"] == "success"
    assert llm.complete_text.call_count == 3  # one research, two outlooks


def test_expired_research_is_not_reused(setup):
    service, db, repo, llm, members = setup
    service.refresh(1, "daily", members, {})
    with db.get_session() as s, s.begin():
        s.scalar(select(EarningsResearch)).expires_at = NOW - timedelta(seconds=1)
    service.refresh(1, "daily", members, {})
    assert llm.complete_text.call_count == 4


def test_final_scan_uses_next_exchange_session_and_bmo_priority(setup):
    service, db, repo, llm, members = setup
    service.clock = lambda: datetime(2026, 7, 2, 20, 10, tzinfo=timezone.utc)
    a, b = NS(id=2, calendar_type="earnings", market="US", market_session="amc"), NS(
        id=3, calendar_type="earnings", market="US", market_session="bmo"
    )
    repo.events = Mock(return_value=[a, b])
    service.refresh = Mock(side_effect=lambda event_id, *args: dict(event_id=event_id, status="cached"))
    result = service.run("final")
    repo.events.assert_called_once_with(date(2026, 7, 6), date(2026, 7, 6))
    assert [r["event_id"] for r in result["results"]] == [3, 2]
    service.clock = lambda: datetime(2026, 7, 3, 20, 10, tzinfo=timezone.utc)
    assert service.run("final")["status"] == "skipped"


def test_review_writes_actual_separately_and_keeps_prediction_unchanged(setup):
    service, db, repo, llm, members = setup
    service.refresh(1, "daily", members, {})
    before = repo.detail(1)["versions"][0]["prediction"]
    service.clock = lambda: datetime(2026, 7, 6, 22, tzinfo=timezone.utc)
    import finance_analysis.database.repositories.earnings_outlook as module

    # Query hook only for this fixture's deterministic wall clock.
    original = module.utc_now
    module.utc_now = service.clock
    try:
        service.collector.actual.return_value = {
            "eps": None,
            "revenue": None,
            "ohlc": {"open": 100, "close": 98, "low": 95, "high": 103},
        }
        result = service.review()
        assert result["results"][0]["status"] == "pending"
        detail = repo.detail(1)
        assert detail["versions"][0]["prediction"] == before
        assert detail["actual"]["close_error"] == 0 and detail["actual"]["range_covered"]
    finally:
        module.utc_now = original


@pytest.mark.parametrize("proof,source_type,expected", [
    ("confirmed", "official", "beat"),
    ("unverified", "official", "unknown"),
    ("confirmed", "news", "unknown"),
])
def test_missing_calendar_quarter_uses_only_verified_release_identity(setup, proof, source_type, expected):
    service, db, repo, llm, members = setup
    with db.get_session() as s, s.begin():
        s.get(FinanceEvent, 1).reporting_period = None
    original = llm.complete_text.side_effect
    estimates = context()["consensus"]

    def call(request, validator):
        if request.call_type == "earnings_research":
            return LLMResult(
                text=json.dumps({
                    "sources": [{
                        "source_id": "ir", "url": "https://example.com/ir",
                        "published_at": NOW.isoformat(), "source_type": source_type,
                    }],
                    "reporting_period": {
                        "value": "2026-Q2", "symbol": "A.US", "event_date": "2026-07-02", "source_ids": ["ir"],
                    },
                    "consensus": {
                        k: {**v, "source_ids": ["ir"], "selection_reason": "same fiscal quarter"}
                        for k, v in estimates.items()
                    },
                }),
                backend="test", search_evidence={"status": proof},
            )
        return original(request, validator)

    llm.complete_text.side_effect = call
    service.refresh(1, "daily", members, {})
    version = repo.detail(1)["versions"][0]
    assert version["prediction"]["eps"]["judgment"] == expected
    assert repo.event(1).reporting_period is None  # Calendar identity/hash is not rewritten.
    if expected == "beat":
        assert version["context"]["event"]["reporting_period"] == "2026-Q2"
        assert version["context"]["reporting_period_evidence"]["source_ids"] == ["ir"]
        with db.get_session() as s, s.begin():
            s.get(FinanceEvent, 1).reporting_period = "2026-Q2"
        summary = display_summary(repo.event(1), repo.state(1), members, NOW)
        assert summary["status"] == "current"
        with db.get_session() as s:
            saved = s.scalar(select(EarningsPrediction))
            service.collector.actual.return_value = {"eps": None, "revenue": None, "ohlc": None}
            assert service._review_one(saved, NOW + timedelta(days=5))["status"] == "pending"
        with db.get_session() as s, s.begin():
            s.get(FinanceEvent, 1).reporting_period = "2026-Q3"
        assert display_summary(repo.event(1), repo.state(1), members, NOW)["status"] == "superseded"
    else:
        assert version["context"]["event"]["reporting_period"] is None


def test_final_retry_keeps_original_event_after_date_rollover(setup):
    service, db, repo, llm, members = setup
    service.clock = lambda: datetime(2026, 7, 2, 5, tzinfo=timezone.utc)
    repo.events = Mock()
    service.refresh = Mock(return_value={"event_id": 1, "status": "success"})
    result = service.run("final", event_id=1)
    assert result["results"][0]["event_id"] == 1
    repo.events.assert_not_called()


def test_busy_events_requeue_until_release_without_rescanning(monkeypatch):
    from finance_analysis.tasks.celery.jobs.earnings_outlook import tasks
    from .test_rules import event

    row = event(id=12, session="bmo")
    service = Mock()
    service.clock.return_value = NOW
    service.repo.event.return_value = row
    service.run.return_value = {"results": [{"event_id": 12, "status": "busy"}]}
    monkeypatch.setattr(tasks, "EarningsOutlookService", lambda: service)
    enqueue = Mock()
    monkeypatch.setattr(tasks.earnings_outlook, "apply_async", enqueue)
    assert tasks._run_outlook("final")["results"][0]["status"] == "deferred"
    enqueue.assert_called_once_with(
        kwargs={"event_id": 12, "stage": "final"}, countdown=60,
        expires=datetime(2026, 7, 2, 4, tzinfo=timezone.utc),
    )
    enqueue.reset_mock()
    service.clock.return_value = datetime(2026, 7, 2, 4, tzinfo=timezone.utc)
    service.run.return_value = {"results": [{"event_id": 12, "status": "busy"}]}
    assert tasks._run_outlook("final", 12)["results"][0]["status"] == "frozen"
    enqueue.assert_not_called()


def test_first_snapshot_outside_seven_days_then_daily_market_refresh(setup):
    service, db, repo, llm, members = setup
    with db.get_session() as s, s.begin():
        s.get(FinanceEvent, 1).event_date = date(2026, 7, 17)
    assert [e.id for e in repo.events(NOW.date(), date(2026, 7, 8), include_unpredicted=True)] == [1]
    assert service.refresh(1, "daily", members, {})["status"] == "success"
    assert repo.events(NOW.date(), date(2026, 7, 8), include_unpredicted=True) == []
    assert service.refresh(1, "daily", members, {})["status"] == "skipped"
    assert llm.complete_text.call_count == 2
    service.clock = lambda: datetime(2026, 7, 10, 15, tzinfo=timezone.utc)
    original = service.collector.collect.side_effect

    def collect(*args):
        value = original(*args)
        value["reference_price"] = 105
        return value

    service.collector.collect.side_effect = collect
    assert service.refresh(1, "daily", members, {})["status"] == "success"
    versions = repo.detail(1)["versions"]
    assert len(versions) == 2
    assert versions[0]["context"]["reference_price"] == 105
    assert versions[1]["context"]["reference_price"] == 100
