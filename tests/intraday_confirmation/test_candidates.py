"""Exercise exact-date/cutoff filtering against a real SQL engine, no production DB."""

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import pytest
from finance_analysis.intraday_confirmation import config as c
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot
from finance_analysis.database.models.confluence import ConfluenceSnapshot
from finance_analysis.database.repositories.intraday_confirmation import CandidateRepository


def test_candidates_only_exact_prior_session_before_freeze(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (Instrument, TrendFollowingSnapshot, ConfluenceSnapshot):
        model.__table__.create(engine)

    class DB:
        @contextmanager
        def get_session(self):
            with Session(engine) as session:
                yield session

    repo = CandidateRepository(DB())
    monkeypatch.setattr(repo.formal, "quant", lambda *args: [])
    day = date(2026, 9, 18)
    cutoff = datetime(2026, 9, 21, 13, 25, tzinfo=timezone.utc)
    with Session(engine) as session, session.begin():
        for i, (trade_date, generated, state, kind) in enumerate(
            [
                (day, cutoff - timedelta(hours=12), "CANDIDATE", "STOCK"),
                (day - timedelta(days=1), cutoff - timedelta(hours=12), "CANDIDATE", "STOCK"),
                (day + timedelta(days=3), cutoff - timedelta(hours=12), "CANDIDATE", "STOCK"),
                (day, cutoff + timedelta(hours=1), "CANDIDATE", "STOCK"),
                (day, cutoff - timedelta(hours=12), "BROKEN", "STOCK"),
                (day, cutoff - timedelta(hours=12), "CANDIDATE", "ETF"),
            ],
            1,
        ):
            code = f"T{i}.US"
            session.add(
                Instrument(
                    id=i,
                    code=code,
                    native_code=f"T{i}",
                    market="US",
                    name=code,
                    instrument_type=kind,
                    currency="USD",
                    source="test",
                )
            )
            session.add(
                TrendFollowingSnapshot(
                    id=i,
                    market="US",
                    code=code,
                    instrument_id=i,
                    universe_key="us_trend",
                    trade_date=trade_date,
                    generated_at=generated,
                    state=state,
                    market_regime="NEUTRAL",
                    market_score=50,
                    rank=i,
                    trend_score=70,
                    rs_score=70,
                    breakout_score=70,
                    alpha_score=70,
                    setup="BREAKOUT_10D",
                    reference_price=100,
                    atr=2,
                    features={},
                    reasons=["昨日趋势"],
                )
            )
    result = repo.candidates("US", day, cutoff)
    assert [row["code"] for row in result] == ["T1.US"]
    assert result[0]["candidate_trade_date"] == day
    assert result[0]["official_trend"]["state"] == "CANDIDATE"
    engine.dispose()


def test_candidate_priority_and_quant_date_cutoff(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (Instrument, TrendFollowingSnapshot, ConfluenceSnapshot):
        model.__table__.create(engine)

    class DB:
        @contextmanager
        def get_session(self):
            with Session(engine) as session:
                yield session

    repo = CandidateRepository(DB())
    day = date(2026, 9, 18)
    cutoff = datetime(2026, 9, 21, 13, 25, tzinfo=timezone.utc)
    with Session(engine) as session, session.begin():
        for i in range(1, 5):
            session.add(
                Instrument(
                    id=i,
                    code=f"T{i}.US",
                    native_code=f"T{i}",
                    market="US",
                    name=f"T{i}",
                    instrument_type="STOCK",
                    currency="USD",
                    source="test",
                )
            )
        session.add(
            ConfluenceSnapshot(
                id=1,
                market="US",
                instrument_id=1,
                trade_date=day,
                generated_at=cutoff - timedelta(days=1),
                confluence_score=90,
                available_weight=85,
                available_signal_count=4,
                positive_signal_count=4,
                eligible=True,
                strong_confluence=True,
                signals={},
                reasons=["强共振"],
                algorithm_version="v1",
            )
        )
    base = dict(trade_date=day, generated_at=cutoff - timedelta(hours=1), signal="BUY", universe_rank=1)
    monkeypatch.setattr(
        repo.formal,
        "quant",
        lambda *args: [
            dict(base, instrument_id=1),
            dict(base, instrument_id=2),
            dict(base, instrument_id=3, trade_date=day - timedelta(days=1)),
            dict(base, instrument_id=4, generated_at=cutoff + timedelta(hours=1)),
        ],
    )
    rows = repo.candidates("US", day, cutoff)
    assert [(r["code"], r["candidate_source"]) for r in rows] == [("T1.US", "confluence"), ("T2.US", "quant")]
    engine.dispose()


@pytest.mark.parametrize(
    ("signal", "rank", "included"),
    [
        ("avoid", 1, False),
        ("avoid", c.QUANT_TOP, False),
        ("avoid", None, False),
        ("buy", c.QUANT_TOP + 1, True),
        ("buy", None, True),
        ("watch", c.QUANT_TOP, True),
        ("watch", c.QUANT_TOP + 1, False),
        ("watch", None, False),
        ("hold", c.QUANT_TOP, True),
        ("hold", c.QUANT_TOP + 1, False),
        ("hold", None, False),
        (None, 1, False),
    ],
)
def test_quant_candidate_signal_contract(monkeypatch, signal, rank, included):
    engine = create_engine("sqlite://")
    for model in (Instrument, TrendFollowingSnapshot, ConfluenceSnapshot):
        model.__table__.create(engine)

    class DB:
        @contextmanager
        def get_session(self):
            with Session(engine) as session:
                yield session

    repo = CandidateRepository(DB())
    day = date(2026, 9, 18)
    cutoff = datetime(2026, 9, 21, 13, 25, tzinfo=timezone.utc)
    with Session(engine) as session, session.begin():
        session.add(
            Instrument(
                id=1,
                code="T1.US",
                native_code="T1",
                market="US",
                name="T1",
                instrument_type="STOCK",
                currency="USD",
                source="test",
            )
        )
    monkeypatch.setattr(
        repo.formal,
        "quant",
        lambda *args: [
            dict(
                instrument_id=1,
                trade_date=day,
                generated_at=cutoff - timedelta(hours=1),
                signal=signal,
                universe_rank=rank,
            )
        ],
    )
    rows = repo.candidates("US", day, cutoff)
    assert [r["code"] for r in rows] == (["T1.US"] if included else [])
    if included:
        assert rows[0]["candidate_source"] == "quant"
    engine.dispose()
