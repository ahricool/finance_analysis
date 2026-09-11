from __future__ import annotations

import pytest

from contextlib import contextmanager
from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from finance_analysis.database.models.etf_rotation import ETFMomentumSnapshot
from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.repositories.etf_rotation import ETFRotationRepository


class _Database:
    def __init__(self):
        self.engine = create_engine("sqlite://")
        Instrument.__table__.create(self.engine)
        ETFMomentumSnapshot.__table__.create(self.engine)

    @contextmanager
    def get_session(self):
        with Session(self.engine) as session:
            yield session

    @contextmanager
    def session_scope(self):
        with Session(self.engine) as session:
            with session.begin():
                yield session


def _snapshot(snapshot_id: int, market: str, instrument_id: int, trade_date: date, rank: int):
    values = {
        "id": snapshot_id,
        "market": market,
        "trade_date": trade_date,
        "instrument_id": instrument_id,
        "rank": rank,
        "previous_5d_return": 0.01,
        "ma20_ratio": 0.01,
        "volume_ratio_5d": 1.0,
        "avg_amount_20d": 1000.0,
        "realized_vol_20d": 0.2,
        "distance_from_20d_high": -0.01,
        "momentum_score": 70.0,
        "entry_score": 75.0,
        "state": "TRENDING",
        "action": "HOLD",
        "overheated": False,
        "candidate_rank": 1,
        "is_candidate": True,
        "score_components": {"base_momentum": 70.0},
        "generated_at": datetime(2026, 8, 27, tzinfo=timezone.utc),
    }
    for window in (1, 5, 10, 20):
        values[f"ret_{window}d"] = 0.01
        values[f"rank_{window}d"] = rank
        values[f"pct_rank_{window}d"] = 90.0
    return ETFMomentumSnapshot(**values)


def test_snapshot_queries_and_historical_dates_are_isolated_by_market() -> None:
    database = _Database()
    with database.session_scope() as session:
        session.add_all(
            [
                Instrument(id=1, market="CN", code="588000.SH", name="CN ETF"),
                Instrument(id=2, market="US", code="SPY.US", name="US ETF"),
            ]
        )
        snapshot_id = 1
        for trade_date, rank in (
            (date(2026, 8, 24), 40),
            (date(2026, 8, 25), 30),
            (date(2026, 8, 26), 20),
            (date(2026, 8, 27), 10),
        ):
            session.add(_snapshot(snapshot_id, "CN", 1, trade_date, rank))
            snapshot_id += 1
        for trade_date, rank in (
            (date(2026, 8, 21), 30),
            (date(2026, 8, 24), 20),
            (date(2026, 8, 25), 10),
            (date(2026, 8, 26), 5),
        ):
            session.add(_snapshot(snapshot_id, "US", 2, trade_date, rank))
            snapshot_id += 1

    cn = ETFRotationRepository("CN", database)
    us = ETFRotationRepository("US", database)
    assert cn.latest_trade_date() == date(2026, 8, 27)
    assert us.latest_trade_date() == date(2026, 8, 26)
    assert cn.available_trade_dates() == [date(2026, 8, 27), date(2026, 8, 26), date(2026, 8, 25), date(2026, 8, 24)]
    assert us.available_trade_dates() == [date(2026, 8, 26), date(2026, 8, 25), date(2026, 8, 24), date(2026, 8, 21)]
    assert {row["market"] for row in cn.snapshots_by_date(date(2026, 8, 24))} == {"CN"}
    assert {row["market"] for row in us.snapshots_by_date(date(2026, 8, 24))} == {"US"}
    assert {row["market"] for row in cn.candidates_by_date(date(2026, 8, 24))} == {"CN"}
    assert {row["market"] for row in us.candidates_by_date(date(2026, 8, 24))} == {"US"}
    assert {row["market"] for row in cn.snapshot_history("588000.SH")} == {"CN"}
    assert {row["market"] for row in us.snapshot_history("SPY.US")} == {"US"}
    assert us.historical_composite_ranks(date(2026, 8, 26), {"SPY.US"}) == {"SPY.US": {1: 10, 3: 30}}


@pytest.fixture(autouse=True)
def offline_ranking_cache(monkeypatch):
    from finance_analysis.etf_rotation import ranking_cache
    monkeypatch.setattr(ranking_cache, "invalidate_market", lambda market: None)


def test_history_filters_as_of_before_limit():
    database = _Database()
    with database.session_scope() as session:
        session.add(Instrument(id=1, market="CN", code="588000.SH", name="ETF"))
        for index in range(3):
            session.add(_snapshot(index + 1, "CN", 1, date(2026, 8, 24 + index), index + 1))
    repository = ETFRotationRepository("CN", database)
    history = repository.snapshot_history("588000.SH", limit=1, as_of=date(2026, 8, 25))
    assert len(history) == 1 and history[0]["trade_date"] == date(2026, 8, 25)
    assert repository.snapshot_history("588000.SH", as_of=date(2026, 8, 23)) == []
    assert set(repository.change_rows(date(2026, 8, 25))[0]) == {"code", "state", "action", "rank", "composite_score"}


def test_market_and_snapshot_overwrite_invalidate_after_commit(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from finance_analysis.etf_rotation import ranking_cache

    committed = []
    session = MagicMock()
    session.execute.return_value.all.return_value = [("588000.SH", 1)]

    @contextmanager
    def transaction():
        yield session
        committed.append("commit")

    def invalidate(market):
        assert committed[-1] == "commit"
        committed.append(market)

    monkeypatch.setattr(ranking_cache, "invalidate_market", invalidate)
    repo = ETFRotationRepository("CN", SimpleNamespace(session_scope=transaction))
    repo.upsert_market_snapshot({"market": "CN", "trade_date": date(2026, 9, 10)})
    repo.upsert_snapshots([{"code": "588000.SH", "market": "CN", "trade_date": date(2026, 9, 10)}])
    assert committed == ["commit", "CN", "commit", "CN"]
