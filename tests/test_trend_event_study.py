from datetime import date, datetime, timedelta, timezone
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
    run_event_study_summary,
    run_event_study_events,
    aggregate_coverage,
    STRATEGIES,
    feature_available,
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
        box_episode_consumed=True,
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
    assert coverage["continuous_complete_since"] is None


def mock_repo(rows, bars=()):
    repo = Mock()
    events = derive_events(rows)
    def query(start, end, strategy="ALL", regime="ALL", *, offset=0, limit=None):
        selected = sorted([e for e in events if (strategy == "ALL" or e["strategy"] == strategy)
                           and (regime == "ALL" or e["regime"] == regime)],
                          key=lambda e: (-e["trade_date"].toordinal(), e["code"], e["strategy"]))
        return (selected[offset:offset + limit] if limit is not None else selected), len(selected)
    repo.event_study_events.side_effect = query
    grouped = {}
    for r in rows:
        key = r["trade_date"], r["market_regime"]
        group = grouped.setdefault(key, {"trade_date": key[0], "market_regime": key[1],
                                         "snapshot_count": 0, **dict.fromkeys(STRATEGIES, 0)})
        group["snapshot_count"] += 1
        for strategy in STRATEGIES:
            group[strategy] += feature_available(r, strategy)
    repo.event_study_coverage.return_value = list(grouped.values())
    repo.event_study_required_bars.side_effect = lambda pairs: [r for r in bars if (r["code"], r["date"]) in pairs]
    return repo


@pytest.mark.parametrize("count", [1, 200])
def test_summary_reads_only_event_paths_and_preserves_evaluation(count):
    plan = following_sessions("US", DAY, 20)
    rows = [{**row(), "code": f"A{i}.US"} for i in range(count)]
    repo = mock_repo(rows, data(plan).values())
    result = run_event_study_summary(repo, "US", DAY, DAY, now=NOW)
    repo.event_study_rows.assert_not_called()
    repo.event_study_events.assert_called_once_with(DAY, DAY, regime="ALL")
    pairs = repo.event_study_required_bars.call_args.args[0]
    assert len(pairs) == count * 21 + 4
    assert ("SPY.US", DAY) in pairs
    assert ("SPY.US", plan[0][0]) not in pairs
    assert result["event_count"] == count * 3
    assert "events" not in result
    assert len(result["groups"]) == 16


def test_sql_filters_events_and_preserves_predecessor_before_start():
    db = _Database()
    StockDaily.__table__.create(db.engine)
    with db.session_scope() as session:
        session.add_all([Instrument(id=1, market="US", code="AAA.US", name="A"),
                         Instrument(id=2, market="US", code="BBB.US", name="B"),
                         Instrument(id=3, market="US", code="OLD.US", name="Old")])
        for year in range(2010, 2026):
            for instrument_id, code in ((1, "AAA.US"), (2, "BBB.US"), (3, "OLD.US")):
                session.add(_snapshot(snapshot_id=year * 10 + instrument_id, code=code,
                                      instrument_id=instrument_id, trade_date=date(year, 1, 2), state="WATCHING"))
        for snapshot_id, day in ((10, date(2026, 9, 16)), (11, DAY)):
            session.add(_snapshot(snapshot_id=snapshot_id, code="BBB.US", instrument_id=2,
                                  trade_date=day, state="TRENDING"))
        for i, (day, state) in enumerate(
            [(date(2026, 9, 17), "CANDIDATE"), (DAY, "TRENDING"), (date(2026, 9, 21), "TRENDING")], 1
        ):
            snapshot = _snapshot(snapshot_id=i, code="AAA.US", instrument_id=1, trade_date=day, state=state)
            snapshot.features = dict(
                box_state="BOX_BREAKOUT" if i == 2 else "NONE",
                box_breakout_fresh=i == 2,
                box_episode_consumed=i >= 2,
                trend_resume=False,
                mr_state="MR_NONE",
            )
            session.add(snapshot)
    queries, compiled = [], []

    def capture(conn, cursor, sql, params, context, executemany):
        from sqlalchemy.dialects import postgresql
        queries.append(sql)
        compiled.append(str(context.compiled.statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
        )))

    event.listen(db.engine, "before_cursor_execute", capture)
    repo = TrendFollowingRepository("US", db)
    result = run_event_study(repo, "US", DAY, date(2026, 9, 21), now=NOW)
    sql = queries[0].lower()
    assert "union all" in sql and "trade_date between" in sql
    assert "LIMIT 1" in compiled[0]
    assert "BETWEEN '2026-09-18' AND '2026-09-21'" in compiled[0]
    assert "study_prior.trade_date <" in sql
    assert "study_prior.instrument_id = trend_following_snapshot.instrument_id" in sql
    assert "score_breakdown" not in queries[0]
    assert result["event_count"] == 2
    assert {e["trade_date"] for e in result["events"]} == {DAY}
    projected, count = repo.event_study_events(DAY, date(2026, 9, 21))
    assert count == len(projected) == 2
    assert {r['code'] for r in projected} == {'AAA.US'}
    assert any("GROUP BY" in query for query in queries)
    for strategy, key in [("BOX_BREAKOUT", "box_breakout_fresh"), ("MEAN_REVERSION", "mr_state"),
                          ("PULLBACK_RESUME", "trend_resume")]:
        query = str(repo._study_event_query(DAY, DAY, strategy, "RISK_ON").compile(
            dialect=__import__('sqlalchemy').dialects.postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        assert key in query.split("WHERE")[1]
        assert "study_prior" not in query  # other strategies do not scan predecessor states



def test_api_range_regime_strategy_validation_and_schema(monkeypatch):
    repo = mock_repo([row()])
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
    coverage = response.json()["box_feature_coverage"]
    assert coverage['continuous_complete_since'] == '2026-09-18'
    assert 'earliest_complete_date' not in coverage
    assert client.get("/event-study", params={**query, "strategy": "PREVIEW"}).status_code == 422
    assert client.get("/event-study", params={**query, "start_date": "2020-01-01"}).status_code == 422
    assert client.get("/event-study", params={**query, "start_date": "2026-09-19"}).status_code == 422


def test_missing_entire_snapshot_day_marks_study_incomplete():
    repo = mock_repo([row()])
    response = run_event_study(repo, "US", DAY, date(2026, 9, 21), now=NOW)
    assert response["missing_snapshot_dates"] == [date(2026, 9, 21)]
    assert all(g["status"] == "insufficient_feature_history" for g in response["groups"])
    assert response["box_feature_coverage"]["continuous_complete_since"] is None
    assert response["mr_feature_coverage"]["continuous_complete_since"] is None


def test_box_retest_rebreakout_produces_one_event_until_new_box():
    from tests.test_trend_following_box import episode_bars, calculate
    bars = episode_bars()
    previous, snapshots = calculate(bars[:60]), []
    for end in range(61, len(bars) + 1):
        previous = calculate(bars[:end], previous_features=previous)
        snapshots.append({**row(), **previous, 'trade_date': bars[end - 1].trade_date})
    box_events = lambda rows: [e for e in derive_events(rows) if e['strategy'] == 'BOX_BREAKOUT']
    assert len(box_events(snapshots[:3])) == 1
    events = box_events(snapshots)
    assert len(events) == 2
    assert [e['trade_date'] for e in events] == [bars[60].trade_date, bars[-1].trade_date]


@pytest.mark.parametrize('missing_last', [False, True])
def test_continuous_coverage_includes_missing_whole_days(missing_last):
    days = [DAY + timedelta(days=i) for i in range(5)]
    rows = [{**row(), 'trade_date': d} for d in days if d != days[3] and (not missing_last or d != days[4])]
    # A single missing feature among existing rows breaks completeness that day.
    rows.append({**row(), 'trade_date': days[1], 'code': 'B.US', 'box_breakout_fresh': None})
    missing = [days[3], days[4]] if missing_last else [days[3]]
    coverage = feature_coverage(rows, 'BOX_BREAKOUT', missing)
    assert coverage['continuous_complete_since'] == (None if missing_last else days[4])
    assert coverage['incomplete_dates'] == sorted([days[1], *missing])
    assert coverage['status'] == 'insufficient_feature_history'


def test_continuous_coverage_is_complete_suffix_not_first_complete_day():
    days = [DAY + timedelta(days=i) for i in range(5)]
    rows = [{**row(), 'trade_date': d, 'mr_state': None if d == days[1] else 'MR_NONE'} for d in days]
    assert feature_coverage(rows, 'MEAN_REVERSION')['continuous_complete_since'] == days[2]
    assert feature_coverage([], 'MEAN_REVERSION')['continuous_complete_since'] is None
    assert feature_coverage([row()], 'MEAN_REVERSION')['continuous_complete_since'] == DAY


def test_study_continuous_suffix_resets_after_missing_session():
    end = date(2026, 9, 22)
    repo = mock_repo([row(), {**row(), 'trade_date': end}])
    response = run_event_study(repo, 'US', DAY, end, now=NOW)
    assert response['missing_snapshot_dates'] == [date(2026, 9, 21)]
    assert response['box_feature_coverage']['continuous_complete_since'] == end
    assert response['mr_feature_coverage']['continuous_complete_since'] == end
    assert all(g['continuous_complete_since'] == end for g in response['groups'] if g['regime'] == 'ALL')


def test_legacy_yesterday_only_freshness_is_insufficient_episode_history():
    old = {**row(), 'box_episode_consumed': None}
    assert feature_coverage([old], 'BOX_BREAKOUT')['status'] == 'insufficient_feature_history'
    assert all(e['strategy'] != 'BOX_BREAKOUT' for e in derive_events([old]))


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_aggregated_coverage_matches_original(strategy):
    rows = [row(), {**row(), "trade_date": DAY + timedelta(days=3), "mr_state": None,
                   "box_episode_consumed": None, "trend_resume": None, "previous_state": None}]
    grouped = mock_repo(rows).event_study_coverage.return_value
    assert aggregate_coverage(grouped, strategy, [DAY + timedelta(days=1)]) == feature_coverage(
        rows, strategy, [DAY + timedelta(days=1)],
    )


def test_second_page_evaluates_only_page_paths(monkeypatch):
    import finance_analysis.trend_following.event_study as study
    rows = [{**row(), "code": f"A{i:03}.US"} for i in range(250)]
    repo = mock_repo(rows)
    original = study.evaluate_event
    spy = Mock(wraps=original)
    monkeypatch.setattr(study, "evaluate_event", spy)
    result = run_event_study_events(repo, "US", DAY, DAY, strategy="BOX_BREAKOUT", offset=100, limit=100, now=NOW)
    assert result["event_count"] == 250
    assert spy.call_count == len(result["events"]) == 100
    assert result["events"][0]["code"] == "A100.US"
    assert {c for c, d in repo.event_study_required_bars.call_args.args[0]} == {
        "SPY.US", *(f"A{i:03}.US" for i in range(100, 200)),
    }
    repo.event_study_coverage.assert_not_called()


def test_sparse_database_events_are_filtered_before_transfer_and_pagination():
    db = _Database()
    StockDaily.__table__.create(db.engine)
    with db.session_scope() as session:
        for i in range(100):
            session.add(Instrument(id=i + 1, market="US", code=f"S{i:03}.US", name=str(i)))
        for i in range(100):
            for d in range(20):
                snapshot = _snapshot(snapshot_id=i * 20 + d + 1, instrument_id=i + 1,
                                     code=f"S{i:03}.US", trade_date=DAY + timedelta(days=d), state="WATCHING")
                snapshot.features = dict(box_state="BOX_BREAKOUT", box_breakout_fresh=i < 3 and d == 2,
                                         box_episode_consumed=True, mr_state="MR_REBOUND" if i < 2 and d == 3 else "MR_NONE",
                                         trend_resume=i == 0 and d == 4)
                session.add(snapshot)
    repo = TrendFollowingRepository("US", db)
    events, count = repo.event_study_events(DAY, DAY + timedelta(days=19))
    assert count == len(events) == 6  # 2,000 snapshots transfer only six events
    coverage = repo.event_study_coverage(DAY, DAY + timedelta(days=19))
    assert len(coverage) == 20
    assert sum(r["snapshot_count"] for r in coverage) == 2000
    queries = []
    event.listen(db.engine, "before_cursor_execute", lambda conn, cursor, sql, *args: queries.append(sql))
    page, total = repo.event_study_events(DAY, DAY + timedelta(days=19), "BOX_BREAKOUT", offset=1, limit=1)
    assert total == 3 and len(page) == 1 and page[0]["code"] == "S001.US"
    assert "LIMIT" in queries[-1] and "OFFSET" in queries[-1]


def test_split_api_default_range_and_no_summary_on_events(monkeypatch):
    import finance_analysis.trend_following.event_study_cache as cache
    from finance_analysis.trend_following.config import DEFAULT_CONFIG
    repo = mock_repo([row()])
    monkeypatch.setattr(api, "TrendFollowingRepository", lambda market: repo)
    monkeypatch.setattr(cache.EventStudyCache, "load", lambda self: None)
    monkeypatch.setattr(cache.EventStudyCache, "save", lambda self, body: None)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.require_current_user] = lambda: SimpleNamespace(id=1)
    client = TestClient(app)
    result = client.get("/event-study/summary", params={"market": "US", "end_date": DAY.isoformat()})
    assert result.status_code == 200
    assert DEFAULT_CONFIG.event_study_default_days == 60
    assert result.json()["start_date"] == (DAY - timedelta(days=60)).isoformat()
    assert "events" not in result.json()
    repo.reset_mock()
    result = client.get("/event-study/events", params={"market": "US", "end_date": DAY.isoformat(),
                                                     "strategy": "BOX_BREAKOUT", "offset": 100})
    assert result.status_code == 200 and result.json()["events"] == []
    repo.event_study_coverage.assert_not_called()
    repo.event_study_required_bars.assert_not_called()
    for path in ("summary", "events"):
        assert client.get(f"/event-study/{path}", params={"strategy": "BOX_BREAKOUT", "start_date": "2020-01-01",
                                                        "end_date": DAY.isoformat()}).status_code == 422


def test_summary_groups_and_page_match_legacy_evaluator_exactly():
    plan = following_sessions("US", DAY, 20)
    rows = [row(), {**row(), "trade_date": plan[0][0], "previous_state": "TRENDING", "market_regime": "RISK_ON"}]
    bars = data(plan)
    repo = mock_repo(rows, bars.values())
    summary = run_event_study_summary(repo, "US", DAY, plan[0][0], now=NOW)
    expected = [evaluate_event(e, following_sessions("US", e["trade_date"], 20), bars, "SPY.US", NOW)
                for e in derive_events(rows)]
    for group in summary["groups"]:
        selected = [e for e in expected if e["strategy"] == group["strategy"]
                    and (group["regime"] == "ALL" or e["regime"] == group["regime"])]
        selected_rows = [r for r in rows if group["regime"] == "ALL" or r["market_regime"] == group["regime"]]
        assert group == aggregate(selected, group["strategy"], group["regime"],
                                  feature_coverage(selected_rows, group["strategy"]))
    page = run_event_study_events(repo, "US", DAY, plan[0][0], strategy="BOX_BREAKOUT", offset=1, limit=1, now=NOW)
    assert page["events"] == [e for e in expected if e["strategy"] == "BOX_BREAKOUT" and e["trade_date"] == DAY]
