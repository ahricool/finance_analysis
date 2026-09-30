from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from finance_analysis.integrations.market_data.research import following_sessions
from finance_analysis.trend_following.event_study import (
    derive_events,
    evaluate_event,
    aggregate,
    feature_coverage,
    run_event_study,
)
from finance_analysis.interfaces.api.v1.endpoints import trend_following as api
from finance_analysis.interfaces.api.v1.schemas.trend_following import EventStudyResponse
from finance_analysis.database.models.stock import StockDaily, Instrument
from finance_analysis.database.repositories.trend_following import TrendFollowingRepository
from tests.test_trend_following_repository import _Database, _snapshot

DAY = date(2026, 9, 18)
NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def row(**kwargs):
    return dict(
        market="US",
        trade_date=DAY,
        code="AAA.US",
        name="A",
        state="TRENDING",
        previous_state="CANDIDATE",
        market_regime="RISK_OFF",
        reference_price=100,
        trend_resume=False,
        box_state="BOX_BREAKOUT",
        box_breakout_fresh=True,
        mr_state="MR_REBOUND",
        **kwargs,
    )


def bar(code, day, close=100):
    return dict(code=code, date=day, open=close, high=close + 2, low=close - 2, close=close, volume=100)


def data(plan):
    bars = {(code, DAY): bar(code, DAY) for code in ("AAA.US", "SPY.US")}
    for i, (day, _) in enumerate(plan, 1):
        for code, multiplier in [("AAA.US", 1), ("SPY.US", 0.5)]:
            bars[code, day] = bar(code, day, 100 + multiplier * i)
    return bars


def test_events_overlap_and_only_use_frozen_event_flags():
    first = row()
    first["trend_resume"] = True
    second = {
        **first,
        "previous_state": "TRENDING",
        "box_state": "NONE",
        "box_breakout_fresh": False,
        "trend_resume": False,
        "mr_state": "MR_OVERSOLD",
    }
    assert {e["strategy"] for e in derive_events([first, second])} == {
        "TREND_FOLLOWING",
        "BOX_BREAKOUT",
        "PULLBACK_RESUME",
        "MEAN_REVERSION",
    }
    assert len(derive_events([first, second])) == 4
    assert derive_events([{**first, "previous_state": None}])[0]["strategy"] != "TREND_FOLLOWING"


def test_exact_targets_excess_mfe_mae_and_signal_regime():
    plan = following_sessions("US", DAY, 20)
    bars = data(plan)
    bars["AAA.US", plan[2][0]]["low"] = 90
    event = derive_events([row()])[0]
    result = evaluate_event(event, plan, bars, "SPY.US", NOW)
    assert result["regime"] == "RISK_OFF"
    assert [p["target_date"] for p in result["horizons"]] == [plan[n - 1][0] for n in (5, 10, 20)]
    for p in result["horizons"]:
        assert p["value"] == pytest.approx(p["days"] / 100)
        assert p["benchmark_return"] == pytest.approx(p["days"] / 200)
        assert p["excess_return"] == pytest.approx(p["days"] / 200)
    assert result["mfe20"] == pytest.approx(0.22)
    assert result["mae20"] == pytest.approx(-0.1)


def test_missing_target_not_shifted_and_partial_path_not_aggregated():
    plan = following_sessions("US", DAY, 20)
    bars = data(plan)
    del bars["AAA.US", plan[4][0]]
    result = evaluate_event(derive_events([row()])[0], plan, bars, "SPY.US", NOW)
    assert result["horizons"][0]["status"] == "missing"
    assert result["horizons"][1]["status"] == "available"  # target-only close return
    assert result["excursion_status"] == "missing"
    assert result["mfe20"] is result["mae20"] is None
    assert result["missing_dates"] == [plan[4][0]]


def test_benchmark_requires_same_base_and_target_not_another_date():
    plan = following_sessions("US", DAY, 20)
    bars = data(plan)
    del bars["SPY.US", plan[9][0]]
    result = evaluate_event(derive_events([row()])[0], plan, bars, "SPY.US", NOW)
    assert result["horizons"][1]["status"] == "available"
    assert result["horizons"][1]["excess_status"] == "missing"
    assert result["horizons"][1]["excess_return"] is None
    assert result["horizons"][0]["excess_return"] is not None


def test_pending_and_zero_return_win_rates_and_denominators():
    plan = following_sessions("US", DAY, 20)
    bars = data(plan)
    bars["AAA.US", plan[4][0]]["close"] = 100
    point = evaluate_event(derive_events([row()])[0], plan, bars, "SPY.US", plan[9][1])
    grouped = aggregate([point], "TREND_FOLLOWING", "ALL", {})
    assert grouped["horizons"][0]["win_rate"] == 0
    assert grouped["horizons"][0]["excess_win_rate"] == 0
    assert grouped["horizons"][1]["matured_count"] == 1
    assert grouped["horizons"][2]["matured_count"] == 0
    assert grouped["horizons"][2]["pending_count"] == 1
    assert grouped["excursion_count"] == 0
    assert grouped["mfe20"]["mean"] is None


def test_calendar_holidays_dst_and_early_close():
    cn = following_sessions("CN", date(2025, 9, 30), 20)
    assert cn[0][0] == date(2025, 10, 9)
    us = following_sessions("US", date(2026, 11, 25), 20)
    assert us[0][0] == date(2026, 11, 27)
    assert us[0][1].hour == 18  # Thanksgiving Friday closes 13:00 EST
    winter = following_sessions("US", date(2026, 10, 30), 1)
    summer = following_sessions("US", date(2026, 10, 29), 1)
    assert winter[0][1].hour == 21
    assert summer[0][1].hour == 20


def test_missing_features_are_not_negative_signals():
    old = {**row(), "mr_state": None, "box_breakout_fresh": None}
    assert {e["strategy"] for e in derive_events([old])} == {"TREND_FOLLOWING"}
    coverage = feature_coverage([old, row()], "BOX_BREAKOUT")
    assert coverage["feature_coverage"] == 0.5
    assert coverage["status"] == "insufficient_feature_history"
    assert coverage["earliest_complete_date"] is None


@pytest.mark.parametrize("count", [1, 200])
def test_study_uses_two_bounded_queries_and_official_context(count):
    plan = following_sessions("US", DAY, 20)
    rows = [{**row(), "code": f"A{i}.US"} for i in range(count)]
    repo = Mock()
    repo.event_study_rows.return_value = rows
    repo.event_study_bars.return_value = list(data(plan).values())
    result = run_event_study(repo, "US", DAY, DAY, now=NOW)
    assert repo.event_study_rows.call_count == repo.event_study_bars.call_count == 1
    assert "SPY.US" in repo.event_study_bars.call_args.args[0]
    assert result["event_count"] == count * 3
    assert len(result["events"]) <= 100
    assert len(result["groups"]) == 16
    EventStudyResponse.model_validate(result)


def test_sql_projection_lag_before_start_and_constant_query_count():
    db = _Database()
    StockDaily.__table__.create(db.engine)
    with db.session_scope() as session:
        session.add(Instrument(id=1, market="US", code="AAA.US", name="A"))
        for i, (day, state) in enumerate(
            [(date(2026, 9, 17), "CANDIDATE"), (DAY, "TRENDING"), (date(2026, 9, 21), "TRENDING")], 1
        ):
            snapshot = _snapshot(snapshot_id=i, code="AAA.US", instrument_id=1, trade_date=day, state=state)
            snapshot.features = dict(
                box_state="BOX_BREAKOUT" if i == 2 else "NONE",
                box_breakout_fresh=i == 2,
                trend_resume=False,
                mr_state="MR_NONE",
            )
            session.add(snapshot)
    queries = []
    event.listen(db.engine, "before_cursor_execute", lambda conn, cursor, sql, *args: queries.append(sql))
    repo = TrendFollowingRepository("US", db)
    result = run_event_study(repo, "US", DAY, date(2026, 9, 21), now=NOW)
    assert len(queries) == 2
    assert "lag(" in queries[0].lower()
    assert "score_breakdown" not in queries[0]
    assert result["event_count"] == 2  # one new TRENDING episode + one fresh Box
    assert {e["trade_date"] for e in result["events"]} == {DAY}


def test_api_range_regime_strategy_validation_and_schema(monkeypatch):
    repo = Mock()
    repo.event_study_rows.return_value = [row()]
    repo.event_study_bars.return_value = []
    monkeypatch.setattr(api, "TrendFollowingRepository", lambda market: repo)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.require_current_user] = lambda: SimpleNamespace(id=1)
    client = TestClient(app)
    query = dict(
        market="US", start_date="2026-09-18", end_date="2026-09-18", strategy="MEAN_REVERSION", regime="RISK_OFF"
    )
    response = client.get("/event-study", params=query)
    assert response.status_code == 200
    assert response.json()["groups"][0]["strategy"] == "MEAN_REVERSION"
    assert response.json()["groups"][0]["regime"] == "RISK_OFF"
    assert client.get("/event-study", params={**query, "strategy": "PREVIEW"}).status_code == 422
    assert client.get("/event-study", params={**query, "start_date": "2020-01-01"}).status_code == 422
    assert client.get("/event-study", params={**query, "start_date": "2026-09-19"}).status_code == 422


def test_missing_entire_snapshot_day_marks_study_incomplete():
    repo = Mock()
    repo.event_study_rows.return_value = [row()]
    repo.event_study_bars.return_value = []
    response = run_event_study(repo, "US", DAY, date(2026, 9, 21), now=NOW)
    assert response["missing_snapshot_dates"] == [date(2026, 9, 21)]
    assert all(g["status"] == "insufficient_feature_history" for g in response["groups"])
