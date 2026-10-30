from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from finance_analysis.database.models.intraday_confirmation import IntradayConfirmationSnapshot, IntradayConfirmationEvaluation
from finance_analysis.database.repositories.intraday_confirmation_store import (
    ConfirmationStore, StaleConfirmationWrite,
)
from finance_analysis.intraday_confirmation.service import ConfirmationService
from finance_analysis.intraday_confirmation.session import Session as TradingSession

DAY = date(2026, 9, 21)
OPEN = datetime(2026, 9, 21, 13, 30, tzinfo=timezone.utc)
TRADING = TradingSession("US", OPEN, OPEN + timedelta(hours=6, minutes=30), date(2026, 9, 18))


@pytest.fixture
def store():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    IntradayConfirmationSnapshot.__table__.create(engine)
    IntradayConfirmationEvaluation.__table__.create(engine)

    class DB:
        @contextmanager
        def get_session(self):
            with Session(engine) as session:
                yield session

        @contextmanager
        def session_scope(self):
            with Session(engine) as session, session.begin():
                yield session

    yield ConfirmationStore(DB())
    engine.dispose()


def frozen(**kwargs):
    return dict(
        market="US", trade_date=DAY, candidate_trade_date=TRADING.previous_date,
        frozen_at=OPEN - timedelta(minutes=5), generated_at=OPEN - timedelta(minutes=5),
        status="frozen", warnings=[], items=[dict(
            code="ABC.US", name="ABC", candidate_source="trend", candidate_reason=["frozen"],
            candidate_trade_date=TRADING.previous_date, source_generated_at=OPEN - timedelta(days=1),
            official_trend={"score": 90}, state="WAIT", metrics={}, trend={}, reasons=[],
            confirmation_score=None, chase_risk="UNKNOWN",
        )], **kwargs,
    )


def evaluation(payload, minute=15, price=105):
    result = deepcopy(payload)
    now = OPEN + timedelta(minutes=minute)
    result.update(status="evaluated", generated_at=now)
    result["items"][0].update(
        state="CONFIRMED", first_confirmed_at=now.isoformat(), first_confirmed_price=price,
        first_confirmed_quote_time=(now - timedelta(seconds=1)).isoformat(), first_confirmation_open=100,
    )
    return result


def test_freeze_is_atomic_immutable_and_survives_new_service(store):
    first = store.save(TRADING, frozen())
    replacement = frozen()
    replacement["items"] = []
    assert store.save(TRADING, replacement) == first
    restarted = ConfirmationStore(store.db)
    assert restarted.load("US", DAY) == first
    assert restarted.load("CN", DAY) is None
    assert restarted.load("US", DAY + timedelta(days=1)) is None
    assert restarted.dates("US") == [DAY]
    assert restarted.dates("CN") == []
    service = ConfirmationService(store=restarted, repository=object(), market_data=object())
    result = service.read("US", trade_date=DAY, now=OPEN + timedelta(days=7))
    assert result["items"][0]["code"] == "ABC.US"
    assert result["items"][0]["return_3d"] is None
    assert "_revision" not in result and "official_trend" not in result["items"][0]


def test_competing_retries_cannot_replace_first_anchor_or_frozen_input(store):
    first = store.save(TRADING, frozen())
    competing = deepcopy(first)
    confirmed = store.save(TRADING, evaluation(first))
    with pytest.raises(StaleConfirmationWrite):
        store.save(TRADING, evaluation(competing, price=999))
    # A normal later evaluation may change the latest status, never first-confirmed evidence.
    later = evaluation(confirmed, minute=30, price=999)
    later["items"][0].update(name="renamed", candidate_reason=["changed"], official_trend={}, state="FAILED")
    saved = store.save(TRADING, later)
    old, new = confirmed["items"][0], saved["items"][0]
    for key in ("first_confirmed_at", "first_confirmed_price", "first_confirmed_quote_time", "first_confirmation_open",
                "name", "candidate_reason", "official_trend"):
        assert new[key] == old[key]
    assert new["state"] == "FAILED"
    assert saved["_revision"] == 3
    with pytest.raises(StaleConfirmationWrite):
        store.save(TRADING, evaluation(saved, minute=1))


def test_null_first_anchor_stays_null_instead_of_using_later_quote(store):
    first = store.save(TRADING, frozen())
    missing = evaluation(first, price=None)
    missing["items"][0]["first_confirmation_open"] = None
    saved = store.save(TRADING, missing)
    saved = store.save(TRADING, evaluation(saved, minute=30, price=999))
    assert saved["items"][0]["first_confirmed_price"] is None
    assert saved["items"][0]["first_confirmation_open"] is None


@pytest.mark.parametrize("change", ["drop", "expand"])
def test_invalid_membership_rolls_back_without_changing_revision(store, change):
    first = store.save(TRADING, frozen())
    bad = evaluation(first)
    bad["items"] = [] if change == "drop" else [*bad["items"], {"code": "NEW.US"}]
    with pytest.raises(ValueError):
        store.save(TRADING, bad)
    assert store.load("US", DAY) == first


def test_failure_to_persist_does_not_report_evaluation_success(monkeypatch):
    from finance_analysis.intraday_confirmation import service as module
    def fail(*args):
        raise RuntimeError("database write unavailable")
    monkeypatch.setattr(module, "collect_data", lambda *args: ({}, {}, {}))
    service = ConfirmationService(store=SimpleNamespace(save=fail), market_data=object())
    with pytest.raises(RuntimeError, match="database write"):
        service._evaluate(TRADING, frozen(), OPEN + timedelta(minutes=15))


def test_busy_database_lock_skips_before_pool_or_network_access(monkeypatch):
    monkeypatch.setattr("finance_analysis.intraday_confirmation.service.resolve_session", lambda *args: TRADING)
    store = SimpleNamespace(lock=lambda *args: nullcontext(SimpleNamespace(acquired=False)))
    service = ConfirmationService(store=store, repository=object(), market_data=object())
    assert service.run("US", OPEN)["status"] == "skipped"


def test_database_lock_is_market_and_day_scoped(store):
    lock = store.lock(TRADING.market, TRADING.day)
    assert lock.lock_id == DAY.toordinal()
    assert lock.db_manager is store.db and not lock.blocking
    assert store.lock("CN", DAY).namespace != lock.namespace


def test_first_stabilized_confirmation_records_exact_quote_and_never_resets(store, monkeypatch):
    from finance_analysis.intraday_confirmation import service as module
    first = store.save(TRADING, frozen())
    now = OPEN + timedelta(minutes=15)
    observations = {"now": now, "price": 105}
    monkeypatch.setattr(module, "monotonic", lambda: 0)
    monkeypatch.setattr(module, "collect_data", lambda *args: ({}, {}, {}))
    monkeypatch.setattr(module, "temporary_trend", lambda *args: {})
    monkeypatch.setattr(module, "metrics", lambda *args: dict(
        price=observations["price"], open=100, quote_time=observations["now"] - timedelta(seconds=1),
        quote_usable=True, data_fresh=True, bar_time=observations["now"], relative_to_market=None,
    ))
    monkeypatch.setattr(module, "decision", lambda *args: dict(
        proposed_state="CONFIRMED", data_status="READY", reasons=[], confirmation_score=99,
    ))
    service = ConfirmationService(store=store, market_data=object())
    service._evaluate(TRADING, first, now)
    pending = store.load("US", DAY)
    assert pending["items"][0]["state"] == "WAIT"
    assert pending["items"][0].get("first_confirmed_price") is None
    observations.update(now=now + timedelta(minutes=5), price=111)
    service._evaluate(TRADING, pending, observations["now"])
    confirmed = store.load("US", DAY)
    anchor = confirmed["items"][0]
    assert anchor["state"] == "CONFIRMED" and anchor["first_confirmed_price"] == 111
    assert datetime.fromisoformat(anchor["first_confirmed_quote_time"]) == observations["now"] - timedelta(seconds=1)
    assert datetime.fromisoformat(anchor["first_confirmed_at"]) == observations["now"]
    observations.update(now=now + timedelta(minutes=30), price=999)
    service._evaluate(TRADING, confirmed, observations["now"])
    repeated = store.load("US", DAY)["items"][0]
    assert repeated["first_confirmed_price"] == 111 and repeated["first_confirmed_at"] == anchor["first_confirmed_at"]
    assert repeated["metrics"]["price"] == 999


def test_historical_api_dates_detail_and_empty_date_are_read_only(store, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from finance_analysis.interfaces.api.v1.endpoints import intraday_confirmation as api
    saved = store.save(TRADING, frozen())
    saved = store.save(TRADING, evaluation(saved))
    monkeypatch.setattr(store, "load_evaluation_bars", lambda pairs: [])
    service = ConfirmationService(store=store, market_data=object(), repository=object())
    app = FastAPI()
    app.include_router(api.router, prefix="/intraday-confirmation")
    app.dependency_overrides[api.get_service] = lambda: service
    app.dependency_overrides[api.require_current_user] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        assert client.get("/intraday-confirmation/dates?market=US").json() == {"dates": [DAY.isoformat()]}
        assert client.get("/intraday-confirmation/dates?market=CN").json() == {"dates": []}
        result = client.get(f"/intraday-confirmation?market=US&trade_date={DAY}").json()
        assert result["trade_date"] == DAY.isoformat()
        row = result["items"][0]
        assert row["first_confirmed_price"] == 105
        assert row["return_3d"] is None and row["return_5d"] is None and row["return_10d"] is None
        assert "first_confirmation_open" not in row and "_revision" not in result
        detail = client.get(f"/intraday-confirmation/ABC.US?market=US&trade_date={DAY}")
        assert detail.status_code == 200 and detail.json() == row
        assert client.get("/intraday-confirmation?market=US&trade_date=2020-01-01").json()["items"] == []
        assert client.get("/intraday-confirmation/ABC.US?market=US&trade_date=2020-01-01").status_code == 404
        assert client.get("/intraday-confirmation?trade_date=not-a-date").status_code == 422
    assert store.load("US", DAY) == saved


def test_history_dates_are_market_scoped_and_daily_baselines_independent(store):
    first = store.save(TRADING, frozen())
    store.save(TRADING, evaluation(first, price=105))
    tomorrow = TradingSession("US", OPEN + timedelta(days=1), TRADING.closed + timedelta(days=1), DAY)
    next_pool = frozen()
    next_pool.update(trade_date=tomorrow.day, candidate_trade_date=DAY, generated_at=tomorrow.opened,
                     frozen_at=tomorrow.opened - timedelta(minutes=5))
    store.save(tomorrow, next_pool)
    assert store.dates("US") == [tomorrow.day, DAY]
    assert store.load("US", tomorrow.day)["items"][0].get("first_confirmed_price") is None
    assert store.load("US", DAY)["items"][0]["first_confirmed_price"] == 105


def test_evaluation_bar_query_is_batched_exact_and_read_only(store):
    from finance_analysis.database.models.stock import Instrument, StockDaily
    engine = None
    with store.db.get_session() as session:
        engine = session.bind
    Instrument.__table__.create(engine)
    StockDaily.__table__.create(engine)
    with store.db.session_scope() as session:
        session.add(Instrument(id=1, market="US", code="ABC.US", native_code="ABC", name="ABC",
                               instrument_type="STOCK", currency="USD", source="test"))
        session.flush()
        for i in range(3):
            session.add(StockDaily(id=i + 1, instrument_id=1, date=DAY + timedelta(days=i),
                                   open=100, high=110, low=99, close=105, volume=1000, data_source="test"))
    loaded = store.load_evaluation_bars({("ABC.US", DAY), ("ABC.US", DAY + timedelta(days=2)), ("MISSING.US", DAY)})
    assert {(r["code"], r["date"]) for r in loaded} == {("ABC.US", DAY), ("ABC.US", DAY + timedelta(days=2))}
    assert all(r["open"] == 100 and r["close"] == 105 for r in loaded)
    assert store.load_evaluation_bars(set()) == []


def test_realized_outcomes_merge_without_overwriting_state_or_first_values(store, monkeypatch):
    from finance_analysis.intraday_confirmation.returns import with_returns
    from finance_analysis.integrations.market_data.research import following_sessions
    saved = store.save(TRADING, frozen())
    saved = store.save(TRADING, evaluation(saved))
    plan = following_sessions("US", DAY, 10)
    generation = OPEN + timedelta(days=20)
    bars = [dict(code="ABC.US", date=d, open=100, high=120, low=90, close=110, volume=100,
                 data_source="test", updated_at=generation) for d in [DAY, *[d for d, _ in plan]]]
    monkeypatch.setattr(store, "load_evaluation_bars", lambda pairs: bars)
    checked = plan[-1][1] + timedelta(seconds=1)
    assert store.pending_returns("US", DAY) == []
    assert len(store.pending_returns("US", DAY + timedelta(days=100))) == 1
    evaluated = with_returns(store, "US", DAY, saved["items"], checked)
    # A more recent state transition can win while the return inputs are being loaded.
    failed = evaluation(saved, minute=30, price=999)
    failed["items"][0]["state"] = "FAILED"
    latest = store.save(TRADING, failed)
    store.save_returns("US", DAY, evaluated, checked)
    realized = store.load("US", DAY)
    item = realized["items"][0]
    assert item["state"] == "FAILED" and item["first_confirmed_price"] == 105
    assert realized["generated_at"] == latest["generated_at"]
    assert set(item["return_evidence"]) == {"3", "5", "10"}
    assert store.pending_returns("US", DAY + timedelta(days=100)) == []
    # An obsolete live payload is rejected rather than dropping the finalized outcomes.
    with pytest.raises(StaleConfirmationWrite):
        store.save(TRADING, evaluation(latest, minute=45))
    changed = deepcopy(evaluated)
    changed[0]["return_evidence"]["3"]["value"] = 999
    store.save_returns("US", DAY, changed, checked + timedelta(days=1))
    assert store.load("US", DAY)["items"][0]["return_evidence"] == item["return_evidence"]
    changed[0]["first_confirmed_price"] = 123
    store.save_returns("US", DAY, changed, checked + timedelta(days=2))
    assert store.load("US", DAY)["items"][0]["return_evidence"] == item["return_evidence"]
    service = ConfirmationService(store=store, market_data=object(), repository=object())
    monkeypatch.setattr(store, "load_evaluation_bars", lambda pairs: (_ for _ in ()).throw(AssertionError("no refetch")))
    public = service.read("US", trade_date=DAY, now=checked + timedelta(days=200))["items"][0]
    assert public["return_3d"] == pytest.approx(110 / 105 - 1)
    assert "return_evidence" not in public


def test_pending_refresh_is_bounded_fair_and_keeps_missing_outcomes_pending(store):
    for offset in range(12):
        trading = TradingSession("US", OPEN + timedelta(days=offset), TRADING.closed + timedelta(days=offset), DAY)
        payload = frozen()
        payload.update(trade_date=trading.day, generated_at=trading.opened)
        initial = store.save(trading, payload)
        updated = evaluation(initial)
        updated["generated_at"] = trading.opened + timedelta(minutes=15)
        store.save(trading, updated)
    pending = store.pending_returns("US", DAY + timedelta(days=100))
    assert len(pending) == 10
    checked = OPEN + timedelta(days=100)
    old_dates = {r["trade_date"] for r in pending}
    for payload in pending:
        store.save_returns("US", date.fromisoformat(payload["trade_date"]), payload["items"], checked)
    next_batch = store.pending_returns("US", DAY + timedelta(days=100))
    assert all(r["trade_date"] not in old_dates for r in next_batch[:2])
    assert len(next_batch) == 10  # Missing bars were not finalized or expired.


def test_manual_outside_session_still_catches_up_historical_outcomes(monkeypatch):
    calls = []
    store = SimpleNamespace(
        lock=lambda *args: nullcontext(SimpleNamespace(acquired=True)),
        pending_returns=lambda *args: calls.append(args) or [],
    )
    monkeypatch.setattr("finance_analysis.intraday_confirmation.service.resolve_session", lambda *args: None)
    result = ConfirmationService(store=store, market_data=object()).run("US", OPEN + timedelta(days=6))
    assert result["status"] == "skipped" and len(calls) == 1


def test_failed_return_write_rolls_back_check_timestamp_and_keeps_pending(store):
    from sqlalchemy import event
    first = store.save(TRADING, frozen())
    saved = store.save(TRADING, evaluation(first))
    with store.db.get_session() as session:
        engine = session.bind
    def fail_update(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE intraday_confirmation_snapshot"):
            raise RuntimeError("simulated outcome write failure")
    event.listen(engine, "before_cursor_execute", fail_update)
    try:
        with pytest.raises(RuntimeError, match="simulated outcome"):
            store.save_returns("US", DAY, saved["items"], OPEN + timedelta(days=20))
    finally:
        event.remove(engine, "before_cursor_execute", fail_update)
    assert store.load("US", DAY) == saved
    with store.db.get_session() as session:
        persisted = session.get(IntradayConfirmationSnapshot, ("US", DAY))
        assert persisted.returns_pending and persisted.returns_checked_at is None


def test_permanently_missing_first_anchor_does_not_fill_pending_queue(store):
    saved = store.save(TRADING, frozen())
    saved = store.save(TRADING, evaluation(saved, price=None))
    assert store.pending_returns("US", DAY + timedelta(days=200)) == []


def test_v2_evaluation_and_snapshot_commit_together_and_are_read_only(store):
    first = store.save(TRADING, frozen(rule_version="intraday_v2"))
    saved = store.save(TRADING, evaluation(first))
    rows = store.evaluations("US", DAY, "ABC.US")
    assert len(rows) == 1 and rows[0]["state"] == "CONFIRMED"
    assert rows[0]["rule_version"] == "intraday_v2"
    assert store.evaluations("CN", DAY, "ABC.US") == []
    assert store.evaluations("US", DAY, "OTHER.US") == []
    with pytest.raises(StaleConfirmationWrite):
        store.save(TRADING, evaluation(first))
    assert len(store.evaluations("US", DAY, "ABC.US")) == 1
    assert store.load("US", DAY) == saved


def test_evaluation_write_failure_rolls_back_snapshot(store, monkeypatch):
    from sqlalchemy import event
    first = store.save(TRADING, frozen(rule_version="intraday_v2"))
    def fail(*args):
        raise RuntimeError("evaluation write failed")
    event.listen(IntradayConfirmationEvaluation, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="evaluation write failed"):
            store.save(TRADING, evaluation(first))
    finally:
        event.remove(IntradayConfirmationEvaluation, "before_insert", fail)
    assert store.load("US", DAY) == first
    assert store.evaluations("US", DAY, "ABC.US") == []
