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


def _snapshot(*, snapshot_id, code, instrument_id, trade_date, state="TRENDING"):
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
        reference_price=110.0,
        atr=2.0,
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
        "universe_size": 3,
        "data_ready_count": 2,
        "data_coverage": 2 / 3,
        "rankable_count": 2,
        "candidate_count": 0,
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
                _snapshot(snapshot_id=1, code="AAA.US", instrument_id=1, trade_date=monday, state="TRENDING"),
                _snapshot(snapshot_id=2, code="BBB.US", instrument_id=2, trade_date=monday, state="WATCHING"),
                _snapshot(snapshot_id=3, code="BBB.US", instrument_id=2, trade_date=tuesday, state="TRENDING"),
                _snapshot(snapshot_id=4, code="AAA.US", instrument_id=1, trade_date=thursday, state="BROKEN"),
            ]
        )
    repository = TrendFollowingRepository("US", database)
    previous = repository.previous_snapshots(wednesday, ["AAA.US", "BBB.US"])
    assert previous["AAA.US"]["trade_date"] == monday
    assert previous["AAA.US"]["state"] == "TRENDING"
    assert previous["BBB.US"]["trade_date"] == tuesday
    assert previous["BBB.US"]["state"] == "TRENDING"
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
                ),
                _snapshot(snapshot_id=2, code="AAPL.US", instrument_id=1, trade_date=date(2026, 6, 2), state="CANDIDATE"),
                _snapshot(snapshot_id=3, code="AAPL.US", instrument_id=1, trade_date=date(2026, 6, 3), state="TRENDING"),
            ]
        )
    repository = TrendFollowingRepository("US", database)
    history = repository.snapshot_history("AAPL.US", limit=60, as_of=date(2026, 6, 1))
    assert [row["trade_date"] for row in history] == [date(2026, 6, 1)]
    assert history[0]["state"] == "CANDIDATE"
    assert all(row["trade_date"] <= date(2026, 6, 1) for row in history)
    latest = repository.snapshot_history("AAPL.US", limit=60)
    assert latest[0]["trade_date"] == date(2026, 6, 3)
    history = repository.snapshot_history("AAPL.US", limit=1, before_trade_date=date(2026, 6, 3))
    assert [row["trade_date"] for row in history] == [date(2026, 6, 2)]
    assert repository.snapshot_history("AAPL.US", limit=60, before_trade_date=date(2026, 6, 1)) == []





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


def test_historical_rank_changes_use_market_snapshot_offsets():
    from finance_analysis.core.ranking import calculate_rank_changes

    db = _Database()
    days = [date(2026, 8, day) for day in (28, 27, 26, 25, 24, 21)]
    with db.session_scope() as session:
        session.add(Instrument(id=1, code="AAPL.US", name="Apple", market="US"))
        for index, day in enumerate(days):
            row = _snapshot(snapshot_id=index + 1, code="AAPL.US", instrument_id=1, trade_date=day)
            row.rank = [15, 20, 27, 30, 42, 50][index]
            session.add(row)
    repository = TrendFollowingRepository("US", db)
    history = repository.historical_composite_ranks(date(2026, 8, 31), ["AAPL.US", "MISSING.US"])
    assert calculate_rank_changes(10, history["AAPL.US"]) == {
        "rank_change_1d": 5, "rank_change_3d": 17, "rank_change_5d": 32,
    }
    assert calculate_rank_changes(10, history.get("MISSING.US", {})) == {
        "rank_change_1d": None, "rank_change_3d": None, "rank_change_5d": None,
    }
    short = repository.historical_composite_ranks(date(2026, 8, 24), ["AAPL.US"])
    assert calculate_rank_changes(10, short["AAPL.US"]) == {
        "rank_change_1d": 40, "rank_change_3d": None, "rank_change_5d": None,
    }
    assert TrendFollowingRepository("CN", db).historical_composite_ranks(date(2026, 8, 31), ["AAPL.US"]) == {}


def _mixed_snapshot_payloads(trade_date):
    payloads = []
    for index, state in enumerate(("CANDIDATE", "WATCHING", "TRENDING"), 1):
        row = _snapshot(
            snapshot_id=index,
            code=f"SYM{index}.US",
            instrument_id=index,
            trade_date=trade_date,
            state=state,
        )
        payload = {
            c.name: getattr(row, c.name)
            for c in TrendFollowingSnapshot.__table__.columns
            if c.name not in {"id", "instrument_id", "generated_at"}
        }
        if state == "WATCHING":
            payload = {
                key: value for key, value in payload.items() if not TrendFollowingSnapshot.__table__.c[key].nullable
            }
            for key in ("features", "score_breakdown", "reasons"):
                payload.pop(key)
        payloads.append(payload)
    return payloads


def test_replace_day_normalizes_mixed_trend_snapshots():
    database = _Database()
    day = date(2026, 9, 7)
    with database.session_scope() as session:
        session.add_all([Instrument(id=i, market="US", code=f"SYM{i}.US", name=f"SYM{i}") for i in range(1, 4)])
    repo = TrendFollowingRepository("US", database)
    assert repo.replace_day(day, _mixed_snapshot_payloads(day), _summary(day)) == 3
    rows = {row["code"]: row for row in repo.snapshots_by_date(day)}
    watching = rows["SYM2.US"]
    assert watching["features"] == watching["score_breakdown"] == {}
    assert watching["reasons"] == []


def test_upsert_normalizes_mixed_records_before_postgresql_compilation():
    from sqlalchemy.dialects import postgresql

    statements = []

    class FakeSession:
        def execute(self, statement):
            statements.append(statement)
            return type("Rows", (), {"all": lambda self: [(f"SYM{i}.US", i) for i in range(1, 4)]})()

    class Database:
        @contextmanager
        def session_scope(self):
            yield FakeSession()

    repo = TrendFollowingRepository("US", Database())
    assert repo.upsert_snapshots(_mixed_snapshot_payloads(date(2026, 9, 7))) == 3
    params = statements[-1].compile(dialect=postgresql.dialect()).params
    assert params["features_m1"] == {}


def test_bulk_paths_validate_required_fields_before_opening_transaction():
    import pytest

    repo = TrendFollowingRepository("US", object())
    day = date(2026, 9, 7)
    for field in ("code", "market", "rank", "reference_price", "atr"):
        for value in ("missing", None):
            payload = _mixed_snapshot_payloads(day)[0]
            if value == "missing":
                payload.pop(field)
            else:
                payload[field] = None
            for write in (
                lambda: repo.upsert_snapshots([payload]),
                lambda: repo.replace_day(day, [payload], _summary(day)),
            ):
                with pytest.raises(ValueError, match=f"required field '{field}' is missing or null"):
                    write()


# Repository tests remain offline even though successful writes now invalidate Redis.
import pytest


@pytest.fixture(autouse=True)
def offline_cache(monkeypatch):
    from finance_analysis.trend_following import ranking_cache
    monkeypatch.setattr(ranking_cache, "invalidate_market", lambda market: None)


def test_read_projections_do_not_load_full_snapshot_or_instrument_json():
    from sqlalchemy import event
    database = _Database()
    with database.session_scope() as session:
        session.add(Instrument(id=1, market="US", code="AAPL.US", name="Apple"))
        row = _snapshot(snapshot_id=1, code="AAPL.US", instrument_id=1, trade_date=date(2026, 9, 10))
        row.features = {"return_5d": 0.15, "unused": {"large": "detail only"}}
        session.add(row)
    statements = []
    event.listen(database.engine, "before_cursor_execute", lambda conn, cursor, statement, *args: statements.append(statement))
    repository = TrendFollowingRepository("US", database)
    items = repository.dashboard_rows(date(2026, 9, 10))
    assert items[0]["return_5d"] == 0.15
    assert "features" not in items[0] and items[0]["score_breakdown"] == {}
    changes = repository.change_rows(date(2026, 9, 10))
    assert set(changes[0]) == {"code", "state", "rank", "trend_score", "rs_score", "alpha_score"}
    assert len(statements) == 2
    assert 'instrument_1' not in statements[0]
    assert 'metadata' not in statements[0]
    assert 'features' not in statements[1]


def test_replace_and_invalidate_clear_cache_only_after_commit(monkeypatch):
    from finance_analysis.trend_following import ranking_cache
    database = _Database()
    repository = TrendFollowingRepository("US", database)
    trade_date = date(2026, 8, 28)
    calls = []

    def invalidated(market):
        # A separate session observes the committed result.
        calls.append((market, repository.latest_trade_date()))

    monkeypatch.setattr(ranking_cache, "invalidate_market", invalidated)
    repository.replace_day(trade_date, [], _summary(trade_date))
    assert calls == [("US", trade_date)]
    repository.replace_day(trade_date, [], _summary(trade_date))
    assert len(calls) == 2
    repository.invalidate_from(trade_date)
    assert calls[-1] == ("US", None)
    with pytest.raises(Exception):
        repository.replace_day(trade_date, [], {"market": "US", "trade_date": trade_date})
    assert len(calls) == 3


def test_dashboard_projection_preserves_all_ranking_metrics_and_boolean_types():
    from finance_analysis.trend_following.read_models import (
        BOOLEAN_FEATURE_FIELDS, NUMERIC_FEATURE_FIELDS, ranking_item,
    )

    db = _Database()
    day = date(2026, 8, 28)
    features = {key: index / 100 for index, key in enumerate(NUMERIC_FEATURE_FIELDS)}
    features.update({key: index % 2 == 0 for index, key in enumerate(BOOLEAN_FEATURE_FIELDS)})
    breakdown = {"trend": {"weighted_r2": 92}, "rs": {"rs_10d": 64},
                 "breakout": {"volume": 80}, "alpha": {"compression": 100}}
    with db.session_scope() as session:
        session.add(Instrument(id=1, code="AAPL.US", name="Apple", market="US"))
        row = _snapshot(snapshot_id=1, code="AAPL.US", instrument_id=1, trade_date=day)
        row.features = features
        row.score_breakdown = breakdown
        session.add(row)
    repository = TrendFollowingRepository("US", db_manager=db)
    result = ranking_item(repository.dashboard_rows(day)[0])
    assert result["features"] == features
    assert all(type(result["features"][key]) is bool for key in BOOLEAN_FEATURE_FIELDS)
    assert result["score_breakdown"] == breakdown
    assert "reasons" not in result
