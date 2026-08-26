from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from finance_analysis.database.models.etf_rotation import ETFMomentumSnapshot
from finance_analysis.database.models.stock import MarketDataSymbol
from finance_analysis.database.repositories.etf_rotation import ETFRotationRepository


class _Database:
    def __init__(self):
        self.engine = create_engine("sqlite://")
        MarketDataSymbol.__table__.create(self.engine)
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


def _snapshot(snapshot_id: int, market: str, symbol_id: int, trade_date: date, rank: int):
    values = {
        "id": snapshot_id,
        "market": market,
        "trade_date": trade_date,
        "symbol_id": symbol_id,
        "previous_5d_return": 0.01,
        "momentum_acceleration": 0.01,
        "ma20_ratio": 0.01,
        "ma60_ratio": 0.01,
        "volume_ratio_5d": 1.0,
        "avg_amount_20d": 1000.0,
        "realized_vol_20d": 0.2,
        "distance_from_20d_high": -0.01,
        "momentum_score": 70.0,
        "entry_score": 75.0,
        "state": "TRENDING",
        "overheated": False,
        "candidate_rank": 1,
        "is_candidate": True,
        "score_components": {"base_momentum": 70.0},
        "generated_at": datetime(2026, 8, 27, tzinfo=timezone.utc),
    }
    for window in (1, 5, 10, 20, 30, 60):
        values[f"ret_{window}d"] = 0.01
        values[f"rank_{window}d"] = rank
        values[f"pct_rank_{window}d"] = 90.0
    return ETFMomentumSnapshot(**values)


def test_snapshot_queries_and_historical_dates_are_isolated_by_market() -> None:
    database = _Database()
    with database.session_scope() as session:
        session.add_all(
            [
                MarketDataSymbol(id=1, market="CN", code="588000.SH", name="CN ETF"),
                MarketDataSymbol(id=2, market="US", code="SPY.US", name="US ETF"),
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
    assert {row["market"] for row in cn.snapshots_by_date(date(2026, 8, 24))} == {"CN"}
    assert {row["market"] for row in us.snapshots_by_date(date(2026, 8, 24))} == {"US"}
    assert {row["market"] for row in cn.candidates_by_date(date(2026, 8, 24))} == {"CN"}
    assert {row["market"] for row in us.candidates_by_date(date(2026, 8, 24))} == {"US"}
    assert {row["market"] for row in cn.snapshot_history("588000.SH")} == {"CN"}
    assert {row["market"] for row in us.snapshot_history("SPY.US")} == {"US"}
    assert us.historical_rank_5d(date(2026, 8, 26), {"SPY.US"}) == {"SPY.US": {1: 10, 3: 30}}
