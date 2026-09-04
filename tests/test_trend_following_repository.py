from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone

from finance_analysis.database.models.stock import Instrument  # pragma: allowlist secret
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot  # pragma: allowlist secret
from finance_analysis.database.repositories.trend_following import TrendFollowingRepository  # pragma: allowlist secret
from finance_analysis.database.models.trend_following import TrendFollowingSummary  # pragma: allowlist secret
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class _Database:
    def __init__(self):
        self.engine = create_engine("sqlite://")
        Instrument.__table__.create(self.engine)
        TrendFollowingSnapshot.__table__.create(self.engine)
        TrendFollowingSummary.__table__.create(self.engine)

    @contextmanager
    def get_session(self):
        with Session(self.engine) as session:
            yield session

    @contextmanager
    def session_scope(self):
        with Session(self.engine) as session:
            with session.begin():
                yield session


def _snapshot(*, snapshot_id, code, instrument_id, trade_date, state="HOLDING", units=1):
    return TrendFollowingSnapshot(
        id=snapshot_id,
        market="US",
        trade_date=trade_date,
        code=code,
        instrument_id=instrument_id,
        universe_key="us_sp500",
        market_regime="RISK_ON",
        market_score=80.0,
        rank=1,
        trend_score=80.0,
        rs_score=80.0,
        breakout_score=70.0,
        alpha_score=80.0,
        features={},
        score_breakdown={},
        setup="BREAKOUT_20D",
        state=state,
        action="HOLD" if state == "HOLDING" else "WATCH",
        reference_price=110.0,
        atr=2.0,
        entry_price=100.0 if units else None,
        signal_date=date(2026, 8, 24) if units else trade_date,
        signal_price=99.0 if units else 110.0,
        units=units,
        opened_at=date(2026, 8, 25) if units else None,
        reasons=["seed"],
        generated_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )


def _summary(trade_date):
    return {
        "market": "US",
        "trade_date": trade_date,
        "universe_key": "us_sp500",
        "benchmark_code": "SPY.US",
        "market_regime": "RISK_ON",
        "market_score": 80.0,
        "suggested_max_exposure": 1.0,
        "universe_size": 3,
        "data_ready_count": 2,
        "data_coverage": 2 / 3,
        "rankable_count": 2,
        "candidate_count": 0,
        "entry_count": 0,
        "add_count": 0,
        "hold_count": 2,
        "reduce_count": 0,
        "exit_count": 0,
        "warnings": [],
        "features": {},
        "score_breakdown": {},
    }


def test_previous_snapshots_are_per_code_and_ignore_missing_days():
    database = _Database()
    monday = date(2026, 8, 24)
    tuesday = date(2026, 8, 25)
    wednesday = date(2026, 8, 26)
    thursday = date(2026, 8, 27)
    with database.session_scope() as session:
        session.add_all(
            [
                Instrument(id=1, market="US", code="AAA.US", name="AAA"),
                Instrument(id=2, market="US", code="BBB.US", name="BBB"),
            ]
        )
        session.add_all(
            [
                _snapshot(snapshot_id=1, code="AAA.US", instrument_id=1, trade_date=monday, state="HOLDING"),
                _snapshot(snapshot_id=2, code="BBB.US", instrument_id=2, trade_date=monday, state="WATCHING", units=0),
                _snapshot(snapshot_id=3, code="BBB.US", instrument_id=2, trade_date=tuesday, state="HOLDING"),
                _snapshot(snapshot_id=4, code="AAA.US", instrument_id=1, trade_date=thursday, state="EXIT", units=0),
            ]
        )
    repository = TrendFollowingRepository("US", database)
    previous = repository.previous_snapshots(wednesday, ["AAA.US", "BBB.US"])
    assert previous["AAA.US"]["trade_date"] == monday
    assert previous["AAA.US"]["state"] == "HOLDING"
    assert previous["AAA.US"]["entry_price"] == 100.0
    assert previous["BBB.US"]["trade_date"] == tuesday
    assert previous["BBB.US"]["state"] == "HOLDING"
    future_safe = repository.previous_snapshots(tuesday, ["AAA.US", "BBB.US"])
    assert future_safe["AAA.US"]["trade_date"] == monday
    assert "thursday" not in {str(row["trade_date"]) for row in future_safe.values()}
    assert all(row["trade_date"] < tuesday for row in future_safe.values())


def test_snapshot_history_is_anchored_to_requested_trade_date():
    database = _Database()
    with database.session_scope() as session:
        session.add(Instrument(id=1, market="US", code="AAPL.US", name="Apple"))
        session.add_all(
            [
                _snapshot(
                    snapshot_id=1,
                    code="AAPL.US",
                    instrument_id=1,
                    trade_date=date(2026, 6, 1),
                    state="CANDIDATE",
                    units=0,
                ),
                _snapshot(snapshot_id=2, code="AAPL.US", instrument_id=1, trade_date=date(2026, 6, 2), state="ENTRY"),
                _snapshot(snapshot_id=3, code="AAPL.US", instrument_id=1, trade_date=date(2026, 6, 3), state="HOLDING"),
            ]
        )
    repository = TrendFollowingRepository("US", database)
    history = repository.snapshot_history("AAPL.US", limit=60, as_of=date(2026, 6, 1))
    assert [row["trade_date"] for row in history] == [date(2026, 6, 1)]
    assert history[0]["state"] == "CANDIDATE"
    assert all(row["trade_date"] <= date(2026, 6, 1) for row in history)
    latest = repository.snapshot_history("AAPL.US", limit=60)
    assert latest[0]["trade_date"] == date(2026, 6, 3)


def test_positions_by_date_only_returns_active_states_with_positive_units():
    database = _Database()
    trade_date = date(2026, 8, 28)
    states = ["ENTRY", "PYRAMIDING", "HOLDING", "WEAKENING", "REDUCE", "EXIT", "CANDIDATE", "HOLDING"]
    with database.session_scope() as session:
        for instrument_id, state in enumerate(states, 1):
            code = f"POS{instrument_id}.US"
            session.add(Instrument(id=instrument_id, market="US", code=code, name=state))
            session.add(
                _snapshot(
                    snapshot_id=instrument_id,
                    code=code,
                    instrument_id=instrument_id,
                    trade_date=trade_date,
                    state=state,
                    units=0 if instrument_id in {7, 8} else 1,
                )
            )

    positions = TrendFollowingRepository("US", database).positions_by_date(trade_date)

    assert {row["state"] for row in positions} == {
        "ENTRY",
        "PYRAMIDING",
        "HOLDING",
        "WEAKENING",
        "REDUCE",
    }
    assert all(row["units"] > 0 for row in positions)
    assert all(row["name"] == row["state"] for row in positions)


def test_replace_day_removes_stale_codes_and_replaces_summary_atomically():
    database = _Database()
    trade_date = date(2026, 8, 28)
    with database.session_scope() as session:
        session.add_all(
            [
                Instrument(id=1, market="US", code="AAA.US", name="AAA"),
                Instrument(id=2, market="US", code="BBB.US", name="BBB"),
                Instrument(id=3, market="US", code="CCC.US", name="CCC"),
            ]
        )
        session.add_all(
            [
                _snapshot(snapshot_id=1, code="AAA.US", instrument_id=1, trade_date=trade_date),
                _snapshot(snapshot_id=2, code="BBB.US", instrument_id=2, trade_date=trade_date),
                _snapshot(snapshot_id=3, code="CCC.US", instrument_id=3, trade_date=trade_date),
            ]
        )
        session.add(TrendFollowingSummary(id=1, generated_at=datetime.now(timezone.utc), **_summary(trade_date)))

    repository = TrendFollowingRepository("US", database)
    replacement = []
    for code in ("AAA.US", "BBB.US"):
        payload = {
            column.name: getattr(
                _snapshot(snapshot_id=10, code=code, instrument_id=1, trade_date=trade_date),
                column.name,
            )
            for column in TrendFollowingSnapshot.__table__.columns
            if column.name not in {"id", "instrument_id", "generated_at"}
        }
        replacement.append(payload)
    summary = {**_summary(trade_date), "universe_size": 2, "data_ready_count": 2, "data_coverage": 1.0}
    assert repository.replace_day(trade_date, replacement, summary) == 2
    assert {row["code"] for row in repository.snapshots_by_date(trade_date)} == {"AAA.US", "BBB.US"}
    stored_summary = repository.summary_by_date(trade_date)
    assert stored_summary is not None
    assert stored_summary["universe_size"] == 2


def test_invalidate_from_removes_only_trend_following_future_chain():
    database = _Database()
    dates = [date(2026, 6, day) for day in range(1, 5)]
    with database.session_scope() as session:
        session.add(Instrument(id=1, market="US", code="AAA.US", name="AAA"))
        for snapshot_id, trade_date in enumerate(dates, 1):
            session.add(
                _snapshot(
                    snapshot_id=snapshot_id,
                    code="AAA.US",
                    instrument_id=1,
                    trade_date=trade_date,
                )
            )
            session.add(
                TrendFollowingSummary(
                    id=snapshot_id,
                    generated_at=datetime.now(timezone.utc),
                    **_summary(trade_date),
                )
            )
    repository = TrendFollowingRepository("US", database)
    repository.invalidate_from(date(2026, 6, 2))
    assert repository.available_trade_dates() == [date(2026, 6, 1)]
    assert repository.snapshot_history("AAA.US", limit=10)[0]["trade_date"] == date(2026, 6, 1)
