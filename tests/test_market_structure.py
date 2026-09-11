from datetime import date, timedelta
from unittest.mock import Mock

import pytest

from finance_analysis.market_structure.metrics import breadth, leadership, rotation_metrics, rotation_velocity, states
from finance_analysis.market_structure.service import MarketStructureService

DAY = date(2026, 9, 1)


def test_breadth_formula_and_synchronized_strength():
    result = breadth(0.03, [0.03] * 100)
    assert result["breadth_divergence_5d"] == pytest.approx(0)
    assert states(result)["breadth"] == "BROAD_STRENGTH"
    result = breadth(0.04, [-0.01, 0, 0.01])
    assert result["breadth_divergence_5d"] == pytest.approx(0.04)
    assert result["member_positive_ratio_5d"] == pytest.approx(1 / 3)
    assert states(result)["breadth"] == "STRONG_DIVERGENCE"


@pytest.mark.parametrize("previous, expected", [({"a": 1, "b": 2, "c": 3}, 0), ({"a": 3, "b": 2, "c": 1}, 100)])
def test_rotation_extremes(previous, expected):
    assert rotation_velocity({"a": 1, "b": 2, "c": 3}, previous) == pytest.approx(expected)


def test_rotation_uses_snapshot_offsets_and_excludes_future():
    ranks = {"a": 1, "b": 2}
    dates = [DAY - timedelta(days=n) for n in (0, 1, 4, 5, 6, 7)]
    snapshots = {d: ranks for d in dates}
    snapshots[dates[3]] = {"a": 2, "b": 1}
    snapshots[DAY + timedelta(days=1)] = {"a": 2, "b": 1}
    result = rotation_metrics(snapshots, DAY)
    assert result == {"rotation_velocity_1d": 0, "rotation_velocity_3d": 100, "rotation_velocity_5d": 0}
    assert rotation_metrics({DAY: ranks}, DAY)["rotation_velocity_1d"] is None
    assert rotation_metrics({dates[1]: ranks}, DAY)["rotation_velocity_1d"] is None


def test_rotation_ties_missing_rank_and_universe_changes():
    assert rotation_velocity({"a": 1, "b": 1, "c": 3}, {"a": 1, "b": 1, "c": 3}) == pytest.approx(0)
    assert rotation_velocity({"a": 1, "b": 1}, {"a": 1, "b": 1}) is None
    assert rotation_velocity({"a": 1}, {"a": 1, "b": 2}) is None
    assert rotation_velocity({"a": None, "b": 2}, {"a": 1, "b": 2}) is None


def test_leadership_extremes_and_no_positive_returns():
    assert leadership([0.1] + [0] * 99) == pytest.approx((1, 100))
    assert leadership([0.01] * 100) == pytest.approx((0.1, 0), abs=1e-10)
    assert leadership([-0.1, 0]) == (None, None)
    assert leadership([]) == (None, None)
    assert leadership([0.1]) == (1, 100)


@pytest.fixture
def engine(monkeypatch):
    import finance_analysis.market_structure.service as module

    sessions = [DAY - timedelta(days=n) for n in range(19, -1, -1)]
    monkeypatch.setattr(module, "get_trading_days_between", lambda *args: sessions)
    monkeypatch.setattr(module, "is_market_open", lambda *args: True)
    monkeypatch.setattr(module, "is_market_session_closed", lambda *args, **kwargs: True)
    monkeypatch.setattr(module, "get_universe_codes", lambda market: {"A.US", "B.US"})
    rows = [
        dict(code=code, trade_date=d, close=100 + i)
        for code in ["A.US", "B.US", "SPY.US"]
        for i, d in enumerate(sessions)
    ]
    # A defensive service boundary must exclude even a broken adapter's future rows.
    rows.append(dict(code="A.US", trade_date=DAY + timedelta(days=1), close=9999))
    repo = Mock()
    repo.load_daily_history.return_value = rows
    repo.etf_rankings.return_value = {DAY: {"ETF1": 1, "ETF2": 2}}
    return MarketStructureService("US", repo), repo


def test_service_batches_and_persists_once(engine):
    service, repo = engine
    assert service.run(DAY)["status"] == "completed"
    repo.load_daily_history.assert_called_once()
    repo.etf_rankings.assert_called_once_with(DAY)
    repo.save.assert_called_once()
    payload = repo.save.call_args.args[0]
    assert payload["breadth_divergence_5d"] == 0
    assert payload["leadership_hhi_5d"] == 0
    assert payload["rotation_velocity_3d"] is None
    assert payload["metrics_json"]["member_count"] == 2


def test_service_dependency_failure_does_not_write(engine):
    service, repo = engine
    repo.etf_rankings.return_value = {}
    with pytest.raises(ValueError, match="ETF Rotation"):
        service.run(DAY)
    repo.save.assert_not_called()
    repo.load_daily_history.assert_not_called()


def test_missing_member_sessions_fail_coverage_not_silently_stale(engine):
    service, repo = engine
    repo.load_daily_history.return_value = [
        r for r in repo.load_daily_history.return_value if not (r["code"] == "A.US" and r["trade_date"] == DAY)
    ]
    with pytest.raises(ValueError, match="coverage"):
        service.run(DAY)
    repo.save.assert_not_called()


def test_read_api_never_runs_calculations(monkeypatch):
    from finance_analysis.interfaces.api.v1.endpoints import market_structure as endpoint

    loader = Mock(return_value={"market": "US", "trade_date": DAY})
    monkeypatch.setattr(endpoint, "read_snapshot", loader)
    monkeypatch.setattr(MarketStructureService, "run", Mock(side_effect=AssertionError("request-time calculation")))
    assert endpoint.snapshot(market="US", trade_date=DAY, user=None)["trade_date"] == DAY
    loader.assert_called_once_with("US", DAY)


def test_backfill_uses_calendar_and_never_auto_runs(monkeypatch):
    import finance_analysis.market_structure.service as module

    service = MarketStructureService("US", Mock())
    service.run = Mock(return_value={"status": "completed"})
    monkeypatch.setattr(module, "get_trading_days_between", lambda *args: [DAY - timedelta(days=1), DAY])
    assert service.backfill(DAY - timedelta(days=3), DAY)["snapshots"] == 2
    assert [call.args[0] for call in service.run.call_args_list] == [DAY - timedelta(days=1), DAY]


def test_universe_reuses_daily_scope_but_excludes_etfs_and_inactive_stocks():
    from types import SimpleNamespace
    from finance_analysis.market_structure.universe import get_universe_codes

    resolver = Mock()
    resolver.resolve_universe.return_value = [
        SimpleNamespace(code="A.US", market="US", instrument_type="STOCK", listing_status="ACTIVE"),
        SimpleNamespace(code="SPY.US", market="US", instrument_type="ETF", listing_status="ACTIVE"),
        SimpleNamespace(code="B.US", market="US", instrument_type="STOCK", listing_status="DELISTED"),
        SimpleNamespace(code="600000.SH", market="CN", instrument_type="STOCK", listing_status="ACTIVE"),
    ]
    assert get_universe_codes("US", resolver) == {"A.US"}
    resolver.resolve_universe.assert_called_once_with("us_daily_sync")


def test_manual_api_validates_range_and_enqueues_without_running(monkeypatch):
    from types import SimpleNamespace
    from pydantic import ValidationError
    from finance_analysis.interfaces.api.v1.schemas.market_structure import MarketStructureRunRequest
    from finance_analysis.interfaces.api.v1.endpoints import market_structure as endpoint
    from finance_analysis.tasks.celery.jobs.market_structure import tasks

    for kwargs in (
        {"start_date": DAY},
        {"start_date": DAY, "end_date": DAY - timedelta(days=1)},
        {"trade_date": DAY, "start_date": DAY, "end_date": DAY},
    ):
        with pytest.raises(ValidationError):
            MarketStructureRunRequest(**kwargs)
    enqueue = Mock(return_value=SimpleNamespace(id="task-1"))
    monkeypatch.setattr(tasks.run_market_structure_cn, "apply_async", enqueue)
    result = endpoint.run(MarketStructureRunRequest(start_date=DAY, end_date=DAY), user=SimpleNamespace(id=7))
    assert result["task_id"] == "task-1"
    assert enqueue.call_args.kwargs["kwargs"]["start_date"] == DAY.isoformat()
    assert enqueue.call_args.kwargs["kwargs"]["_triggered_by_uid"] == 7
    assert enqueue.call_args.kwargs["queue"] == "analysis"


def test_market_tasks_follow_etf_schedule_and_are_independent():
    from finance_analysis.tasks.celery.schedule import require_scheduled_task_definition

    for market in ("cn", "us"):
        current = require_scheduled_task_definition(f"market_structure_{market}")
        etf = require_scheduled_task_definition(f"etf_rotation_{market}")
        assert current.timezone == etf.timezone
        assert current.schedules[0].hour == etf.schedules[0].hour
        assert int(current.schedules[0].minute) > int(etf.schedules[0].minute)
        assert current.celery_task_name != etf.celery_task_name
        assert current.allow_manual_run
