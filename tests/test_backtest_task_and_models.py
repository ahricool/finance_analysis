from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from finance_analysis.backtest.service import BacktestService
from finance_analysis.backtest.types import BacktestResult
from finance_analysis.database.models.backtest import BacktestEquity, BacktestRun, BacktestTrade


def run_row(engine="backtrader"):
    return SimpleNamespace(
        id=12,
        engine=engine,
        strategy_key="sma_cross",
        market="US",
        code="AAPL.US",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 2, 1),
    )


class FakeBacktests:
    def __init__(self, row):
        self.row = row
        self.failed = []
        self.completed = []

    def claim_run(self, run_id):
        return self.row if run_id == self.row.id else None

    def update_progress(self, run_id, progress):
        pass

    def complete_run(self, run_id, result):
        self.completed.append((run_id, result))

    def fail_run(self, run_id, error):
        self.failed.append((run_id, error))


def test_worker_dispatches_exact_engine_and_returns_small_task_result(monkeypatch):
    repository = FakeBacktests(run_row("backtrader"))
    service = BacktestService(backtests=repository, symbols=SimpleNamespace(), stocks=SimpleNamespace())
    request = SimpleNamespace()
    monkeypatch.setattr(service, "_request_for_run", lambda run: request)

    result = BacktestResult(
        engine="backtrader", engine_version="1.9.78.123", strategy_key="sma_cross", market="US",
        code="AAPL.US", start_date=date(2025, 1, 1), end_date=date(2025, 2, 1), trades=[], equity_curve=[],
        summary={"total_return_pct": 1.25},
    )
    calls = []

    class Engine:
        def run(self, received):
            calls.append(received)
            return result

    monkeypatch.setattr("finance_analysis.backtest.service.create_engine", lambda key: Engine())
    payload = service.execute_run(12)
    assert calls == [request]
    assert payload == {
        "backtest_run_id": 12, "engine": "backtrader", "strategy_key": "sma_cross",
        "status": "completed", "trade_count": 0, "total_return_pct": 1.25,
    }
    assert repository.completed


def test_worker_failure_marks_same_run_failed_without_engine_fallback(monkeypatch):
    repository = FakeBacktests(run_row("rqalpha"))
    service = BacktestService(backtests=repository, symbols=SimpleNamespace(), stocks=SimpleNamespace())
    monkeypatch.setattr(service, "_request_for_run", lambda run: SimpleNamespace())
    requested = []

    class Engine:
        def run(self, request):
            raise RuntimeError("rqalpha execution failed")

    monkeypatch.setattr(
        "finance_analysis.backtest.service.create_engine",
        lambda key: requested.append(key) or Engine(),
    )
    with pytest.raises(RuntimeError, match="rqalpha execution failed"):
        service.execute_run(12)
    assert requested == ["rqalpha"]
    assert repository.failed and "rqalpha execution failed" in repository.failed[0][1]


def test_backtest_model_constraints_and_indexes_are_registered():
    run_constraints = {item.name for item in BacktestRun.__table__.constraints}
    run_indexes = {item.name for item in BacktestRun.__table__.indexes}
    trade_indexes = {item.name for item in BacktestTrade.__table__.indexes}
    equity_constraints = {item.name for item in BacktestEquity.__table__.constraints}
    assert {"ck_backtest_run_engine", "ck_backtest_run_status", "ck_backtest_run_progress"} <= run_constraints
    assert {
        "ix_backtest_run_uid_created_at", "ix_backtest_run_engine_created_at",
        "ix_backtest_run_strategy_created_at", "ix_backtest_run_status_created_at",
    } <= run_indexes
    assert {"ix_backtest_trade_run_date", "ix_backtest_trade_run_code"} <= trade_indexes
    assert "uix_backtest_equity_run_date" in equity_constraints
