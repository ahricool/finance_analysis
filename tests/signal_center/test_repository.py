"""Isolated PostgreSQL migration, input immutability and raw source date boundaries."""

import importlib.util
import os
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from finance_analysis.core.time import utc_now
from finance_analysis.database.models.signal_center import SignalCenterRun
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot
from finance_analysis.database.models.industry_strength import IndustryStrengthSnapshot, IndustryStrengthConstituent
from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.repositories.signal_center import SignalCenterRepository
from finance_analysis.database.base import Base


@pytest.fixture
def repo():
    url = os.getenv("SIGNAL_CENTER_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Requires isolated test PostgreSQL")
    engine = create_engine(url)
    schema = "signal_test_" + uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = engine.execution_options(schema_translate_map={None: schema})

    class DB:
        @contextmanager
        def get_session(self):
            with Session(scoped) as session:
                yield session

        @contextmanager
        def session_scope(self):
            with Session(scoped) as session, session.begin():
                yield session

        def connect(self):
            return scoped.connect()

    spec = importlib.util.spec_from_file_location(
        "migration", Path(__file__).parents[2] / "alembic/versions/0067_signal_center.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    try:
        with scoped.begin() as conn:
            Base.metadata.create_all(
                conn, tables=[t for t in Base.metadata.sorted_tables if t.name != "signal_center_run"]
            )
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            migration.op = Operations(MigrationContext.configure(conn))
            migration.upgrade()
            assert {c["name"] for c in inspect(conn).get_columns("signal_center_run", schema=schema)} == set(
                SignalCenterRun.__table__.c.keys()
            )
        yield SignalCenterRepository(DB())
        with engine.begin() as conn:
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            migration.op = Operations(MigrationContext.configure(conn))
            migration.downgrade()
            assert not inspect(conn).has_table("signal_center_run", schema=schema)
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def test_daily_unique_immutable_inputs_and_checked_decision(repo):
    day = date(2026, 9, 22)
    fields = dict(
        status="pending", candidate_snapshot={"candidates": []}, prompt_version="v1", system_prompt="s", prompt="p"
    )
    repo.create("CN", day, **fields)
    with pytest.raises(IntegrityError):
        repo.create("CN", day, **fields)
    with pytest.raises(ValueError):
        repo.finish("CN", day, candidate_snapshot={})
    with pytest.raises(IntegrityError):
        repo.finish("CN", day, status="completed", decision="BUY", confidence="high", analysis={})
    repo.finish("CN", day, status="completed", decision="NO_TRADE", confidence="low", analysis={"thesis": "skip"})
    repo.finish("CN", day, decision="BUY", selected_symbol="600000.SH")
    assert repo.get("CN", day)["decision"] == "NO_TRADE"
    repo.create("US", day, **fields)
    assert len(repo.history()) == 2
    assert repo.get("CN", day)["candidate_snapshot"] == {"candidates": []}


def test_trend_previous_state_and_no_latest_fallback(repo):
    day = date(2026, 9, 22)
    with repo.db.session_scope() as s:
        s.add(
            Instrument(
                id=1,
                market="CN",
                code="600000.SH",
                name="test",
                native_code="600000",
                instrument_type="STOCK",
                currency="CNY",
                source="test",
            )
        )
        for d, rank in [(day - timedelta(days=1), 20), (day, 1)]:
            s.add(
                TrendFollowingSnapshot(
                    market="CN",
                    trade_date=d,
                    code="600000.SH",
                    instrument_id=1,
                    universe_key="CN",
                    market_regime="NEUTRAL",
                    market_score=50,
                    rank=rank,
                    trend_score=80,
                    rs_score=80,
                    breakout_score=80,
                    alpha_score=80,
                    setup="BREAKOUT",
                    state="TRENDING",
                    reference_price=10,
                    atr=1,
                )
            )
    rows = repo.trend("CN", day)
    assert rows[0]["rank_change"] == 19
    assert rows[0]["previous_trade_date"] == day - timedelta(days=1)
    assert repo.trend("CN", day + timedelta(days=1)) == []
    assert repo.trend("US", day) == []


def test_industry_requires_matching_latest_generation(repo):
    day, now = date(2026, 9, 22), utc_now()
    with repo.db.session_scope() as s:
        for d in [day - timedelta(days=1), day]:
            s.add(
                IndustryStrengthSnapshot(
                    trade_date=d,
                    industry_code="I",
                    industry_name="test",
                    state="STRONG",
                    data_timestamp=now,
                    members_observed_at=now,
                    quality={},
                    updated_at=now,
                )
            )
        s.add(
            IndustryStrengthConstituent(
                industry_code="I", stock_code="600000.SH", stock_name="test", trend_rank=1, updated_at=now
            )
        )
    assert len(repo.industry("CN", day)) == 1
    assert repo.industry("CN", day - timedelta(days=1)) == []
    with repo.db.session_scope() as s:
        row = s.query(IndustryStrengthConstituent).one()
        row.updated_at = now + timedelta(seconds=1)
    assert repo.industry("CN", day) == []
