"""Prior-day selection mirrors formal ranks; observations and Quant never enter V2."""

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.models.trend_following import TrendFollowingSnapshot as Trend
from finance_analysis.database.models.confluence import ConfluenceSnapshot as Confluence
from finance_analysis.database.models.etf_rotation import ETFMomentumSnapshot as ETF
from finance_analysis.database.repositories.intraday_confirmation import CandidateRepository

DAY = date(2026, 9, 18)
CUTOFF = datetime(2026, 9, 21, 13, 20, tzinfo=timezone.utc)
GENERATED = CUTOFF - timedelta(days=1)


class DB:
    def __init__(self):
        self.engine = create_engine("sqlite://")
        for model in (Instrument, Trend, Confluence, ETF):
            model.__table__.create(self.engine)

    @contextmanager
    def get_session(self):
        with Session(self.engine) as session:
            yield session


def stock(i, kind="STOCK"):
    return Instrument(
        id=i,
        code=f"T{i}.US",
        market="US",
        name=f"T{i}",
        instrument_type=kind,
        currency="USD",
        source="test",
        listing_status="ACTIVE",
    )


def trend(i, rank, **updates):
    return Trend(
        **dict(
            dict(
                id=i,
                instrument_id=i,
                code=f"T{i}.US",
                market="US",
                trade_date=DAY,
                generated_at=GENERATED,
                trend_period=20,
                universe_key="us_trend",
                state="WATCHING",
                market_regime="NEUTRAL",
                market_score=50,
                rank=rank,
                trend_score=70,
                rs_score=70,
                breakout_score=70,
                alpha_score=70,
                setup="BREAKOUT_10D",
                reference_price=100,
                atr=2,
                features={},
                reasons=["趋势"],
            ),
            **updates,
        )
    )


def confluence(i, eligible=True, **updates):
    return Confluence(
        **dict(
            dict(
                id=i,
                instrument_id=i,
                market="US",
                trade_date=DAY,
                generated_at=GENERATED,
                confluence_score=65,
                available_weight=85,
                available_signal_count=4,
                positive_signal_count=4,
                eligible=eligible,
                strong_confluence=False,
                signals={},
                reasons=["共振精选"],
                algorithm_version="confluence_v2_2",
            ),
            **updates,
        )
    )


def etf(i, rank, **updates):
    fields = dict(
        id=i,
        instrument_id=i,
        market="US",
        trade_date=DAY,
        generated_at=GENERATED,
        rank=rank,
        previous_5d_return=0.01,
        ma20_ratio=0.01,
        realized_vol_20d=0.2,
        distance_from_20d_high=-0.01,
        momentum_score=70,
        entry_score=75,
        state="TRENDING",
        overheated=False,
        is_candidate=False,
        score_components={},
    )
    for w in (1, 5, 10, 20):
        fields.update({f"ret_{w}d": 0.01, f"rank_{w}d": rank, f"pct_rank_{w}d": 90})
    return ETF(**{**fields, **updates})


def test_all_selected_not_strong_plus_top30_and_top5_without_global_truncation():
    db = DB()
    with db.get_session() as s, s.begin():
        s.add_all([stock(i) for i in range(1, 50)])
        s.add_all([confluence(i) for i in range(1, 11)])
        s.add(confluence(11, eligible=False, confluence_score=90))
        s.add_all([trend(i, i - 11) for i in range(12, 43)])
        s.add_all([etf(i, i - 42) for i in range(43, 49)])
    rows = CandidateRepository(db).candidates("US", DAY, CUTOFF)
    assert len(rows) == 45
    assert "T11.US" not in {r["code"] for r in rows}  # High score but observation only.
    assert "T42.US" not in {r["code"] for r in rows}  # rank 31
    assert "T48.US" not in {r["code"] for r in rows}  # rank 6
    assert {r["candidate_source"] for r in rows} == {"confluence", "trend", "etf"}
    assert all(r["instrument_type"] == "ETF" and r["official_trend"] is None for r in rows[-5:])
    db.engine.dispose()


def test_sources_merge_and_preserve_formal_dates_ranks_reasons():
    db = DB()
    with db.get_session() as s, s.begin():
        s.add(stock(1, "ETF"))
        s.add_all([confluence(1), trend(1, 3), etf(1, 2)])
    rows = CandidateRepository(db).candidates("US", DAY, CUTOFF)
    assert len(rows) == 1
    row = rows[0]
    assert row["candidate_sources"] == ["confluence", "trend", "etf"]
    assert [r["rank"] for r in row["source_evidence"]] == [None, 3, 2]
    assert row["official_trend"]["state"] == "WATCHING"
    assert len(row["candidate_reason"]) == 4
    db.engine.dispose()


def test_exact_date_cutoff_active_and_period_boundaries():
    db = DB()
    with db.get_session() as s, s.begin():
        s.add_all([stock(i) for i in range(1, 10)])
        s.add_all(
            [
                trend(1, 1),
                trend(2, 2, trade_date=DAY - timedelta(days=1)),
                trend(3, 3, generated_at=CUTOFF),
                trend(4, 4, trend_period=40),
                trend(5, 5, trend_period=60),
                trend(6, 6),
            ]
        )
        s.add(etf(7, 1, generated_at=CUTOFF + timedelta(minutes=1)))
        s.add(confluence(8, trade_date=DAY + timedelta(days=3)))
        s.flush()
        s.get(Instrument, 6).listing_status = "DELISTED"
    rows = CandidateRepository(db).candidates("US", DAY, CUTOFF)
    assert [r["code"] for r in rows] == ["T1.US"]
    assert CandidateRepository(db).candidates("CN", DAY, CUTOFF) == []
    db.engine.dispose()
