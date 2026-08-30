from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone

from finance_analysis.database.models.stock import MarketDataSymbol  # pragma: allowlist secret
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot  # pragma: allowlist secret
from finance_analysis.database.repositories.trend_following import TrendFollowingRepository  # pragma: allowlist secret
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class _Database:
    def __init__(self):
        self.engine = create_engine("sqlite://")
        MarketDataSymbol.__table__.create(self.engine)
        TrendFollowingSnapshot.__table__.create(self.engine)

    @contextmanager
    def get_session(self):
        with Session(self.engine) as session:
            yield session

    @contextmanager
    def session_scope(self):
        with Session(self.engine) as session:
            with session.begin():
                yield session


def _snapshot(*, snapshot_id, code, symbol_id, trade_date, state="HOLDING", units=1):
    return TrendFollowingSnapshot(
        id=snapshot_id,
        market="US",
        trade_date=trade_date,
        code=code,
        symbol_id=symbol_id,
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
        intraday_confirmation="UNAVAILABLE",
        generated_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )


def test_previous_snapshots_are_per_code_and_ignore_missing_days():
    database = _Database()
    monday = date(2026, 8, 24)
    tuesday = date(2026, 8, 25)
    wednesday = date(2026, 8, 26)
    thursday = date(2026, 8, 27)
    with database.session_scope() as session:
        session.add_all([
            MarketDataSymbol(id=1, market="US", code="AAA.US", name="AAA"),
            MarketDataSymbol(id=2, market="US", code="BBB.US", name="BBB"),
        ])
        session.add_all([
            _snapshot(snapshot_id=1, code="AAA.US", symbol_id=1, trade_date=monday, state="HOLDING"),
            _snapshot(snapshot_id=2, code="BBB.US", symbol_id=2, trade_date=monday, state="WATCHING", units=0),
            _snapshot(snapshot_id=3, code="BBB.US", symbol_id=2, trade_date=tuesday, state="HOLDING"),
            _snapshot(snapshot_id=4, code="AAA.US", symbol_id=1, trade_date=thursday, state="EXIT", units=0),
        ])
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
        session.add(MarketDataSymbol(id=1, market="US", code="AAPL.US", name="Apple"))
        session.add_all([
            _snapshot(snapshot_id=1, code="AAPL.US", symbol_id=1, trade_date=date(2026, 6, 1), state="CANDIDATE", units=0),
            _snapshot(snapshot_id=2, code="AAPL.US", symbol_id=1, trade_date=date(2026, 6, 2), state="ENTRY"),
            _snapshot(snapshot_id=3, code="AAPL.US", symbol_id=1, trade_date=date(2026, 6, 3), state="HOLDING"),
        ])
    repository = TrendFollowingRepository("US", database)
    history = repository.snapshot_history("AAPL.US", limit=60, as_of=date(2026, 6, 1))
    assert [row["trade_date"] for row in history] == [date(2026, 6, 1)]
    assert history[0]["state"] == "CANDIDATE"
    assert all(row["trade_date"] <= date(2026, 6, 1) for row in history)
    latest = repository.snapshot_history("AAPL.US", limit=60)
    assert latest[0]["trade_date"] == date(2026, 6, 3)
