from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from finance_analysis.analysis.signal_evaluation import (
    SignalEvaluationService,
    build_initial_evaluation,
)
from finance_analysis.database.models.signal import Signal
from finance_analysis.tasks.celery.jobs.a_share_intraday_analysis.notifications import (
    AShareIntradayReporter,
)
from finance_analysis.tasks.celery.jobs.us_intraday_analysis.notifications import SignalReporter

UTC = timezone.utc


class FakeSignalRepository:
    def __init__(self, rows):
        self.rows = list(rows)
        self.queries = []
        self.updates = []

    def list_for_evaluation(self, *, market, signal_at_from, limit, cursor=None):
        self.queries.append((market, signal_at_from, limit, cursor))
        eligible = sorted(
            (
                row
                for row in self.rows
                if row.market == market and row.signal_at >= signal_at_from
                and (cursor is None or (row.signal_at, row.id) > cursor)
            ),
            key=lambda row: (row.signal_at, row.id),
        )
        return eligible[:limit]

    def update_evaluation(self, signal_id, evaluation):
        self.updates.append((signal_id, dict(evaluation)))
        next(row for row in self.rows if row.id == signal_id).evaluation = dict(evaluation)


class FakeStockRepository:
    def __init__(self, bars=()):
        self.bars = list(bars)
        self.calls = []

    def get_forward_bars(self, **kwargs):
        self.calls.append(kwargs)
        return self.bars[: kwargs["eval_window_days"]]


class FakeMinuteBars:
    def __init__(self, bars=()):
        self.bars = list(bars)
        self.calls = []

    def get_stored_bars(self, symbol, count, *, market_type):
        self.calls.append((symbol, count, market_type))
        return list(self.bars)


def make_signal(*, signal_id=1, market="CN", signal_at=None, evaluation=None):
    row = Signal(
        market=market,
        code="600519" if market == "CN" else "AAPL",
        price=100.0,
        signal_at=signal_at or datetime(2026, 6, 30, 6, 55, tzinfo=UTC),
        evaluation=evaluation if evaluation is not None else {},
    )
    row.id = signal_id
    return row


def minute_bars(start, count):
    return [
        {
            "timestamp": (start + timedelta(minutes=index)).isoformat(),
            "open": 100 + index / 10,
            "high": 101 + index / 10,
            "low": 99 + index / 10,
            "close": 100.5 + index / 10,
        }
        for index in range(count)
    ]


def daily_bars(count):
    return [
        SimpleNamespace(close=101 + index, high=102 + index, low=99 + index)
        for index in range(count)
    ]


def service(rows, *, minutes=(), daily=(), batch_size=200):
    signals = FakeSignalRepository(rows)
    stocks = FakeStockRepository(daily)
    minute_source = FakeMinuteBars(minutes)
    evaluator = SignalEvaluationService(
        signal_repository=signals,
        stock_repository=stocks,
        minute_bar_source=minute_source,
        batch_size=batch_size,
    )
    return evaluator, signals, stocks, minute_source


def test_initial_evaluation_distinguishes_intraday_and_non_intraday():
    assert build_initial_evaluation(supports_intraday=True) == {}
    assert build_initial_evaluation(supports_intraday=False) == {
        "30m": {"status": "not_applicable", "reason": "non_intraday_signal"},
        "1h": {"status": "not_applicable", "reason": "non_intraday_signal"},
    }


@pytest.mark.parametrize(
    ("reporter", "signal", "market", "code"),
    [
        (
            AShareIntradayReporter(),
            SimpleNamespace(
                code="600519",
                name="贵州茅台",
                signal_type="breakout",
                metrics={"price": 1500},
            ),
            "CN",
            "600519",
        ),
        (
            SignalReporter(),
            SimpleNamespace(
                symbol="AAPL",
                signal_type="breakout",
                metrics={"price": 200},
            ),
            "US",
            "AAPL",
        ),
    ],
)
def test_current_intraday_signal_writers_start_with_empty_evaluation(
    reporter,
    signal,
    market,
    code,
):
    signal_at = datetime(2026, 6, 30, 14, 55, tzinfo=UTC)
    with patch(
        "finance_analysis.database.repositories.signal.SignalRepository"
    ) as repository_class:
        repository_class.return_value.create.return_value = SimpleNamespace(id=42)

        assert reporter.persist_signal(signal, signal_at) == 42

    kwargs = repository_class.return_value.create.call_args.kwargs
    assert kwargs["market"] == market
    assert kwargs["code"] == code
    assert kwargs["evaluation"] == {}


@pytest.mark.parametrize("market", ["CN", "US"])
def test_market_query_is_limited_to_last_15_natural_days_and_paginated(market):
    now = datetime(2026, 6, 30, 12, tzinfo=UTC)
    recent = make_signal(market=market, signal_at=now - timedelta(days=15))
    old = make_signal(signal_id=2, market=market, signal_at=now - timedelta(days=15, seconds=1))
    other = make_signal(signal_id=3, market="US" if market == "CN" else "CN", signal_at=now)
    evaluator, repository, _, _ = service([recent, old, other], batch_size=1)

    result = evaluator.evaluate_signals(market=market, now=now)

    assert result["market"] == market
    assert result["scanned_signals"] == 1
    assert all(query[0] == market for query in repository.queries)
    assert all(query[1] == now - timedelta(days=15) for query in repository.queries)


def test_existing_results_and_not_applicable_periods_are_not_overwritten_but_daily_is_added():
    existing_30m = {"price": 999, "return_pct": 1}
    row = make_signal(
        evaluation={
            "30m": existing_30m,
            "1h": {"status": "not_applicable", "reason": "non_intraday_signal"},
        }
    )
    evaluator, repository, stocks, minute_source = service([row], daily=daily_bars(7))

    result = evaluator.evaluate_signals(market="CN", now=datetime(2026, 7, 10, tzinfo=UTC))

    saved = repository.updates[0][1]
    assert saved["30m"] == existing_30m
    assert saved["1h"]["status"] == "not_applicable"
    assert {"1d", "3d", "7d"}.issubset(saved)
    assert minute_source.calls == []
    assert stocks.calls[0]["market"] == "CN"
    assert result["not_applicable_skipped"] == 1


@pytest.mark.parametrize(
    ("market", "zone", "local_signal_time"),
    [
        ("CN", "Asia/Shanghai", (2026, 6, 30, 14, 55)),
        ("US", "America/New_York", (2026, 6, 30, 15, 55)),
    ],
)
def test_late_signal_waits_then_accumulates_minutes_across_trading_days(
    market,
    zone,
    local_signal_time,
):
    local = ZoneInfo(zone)
    signal_at = datetime(*local_signal_time, tzinfo=local)
    row = make_signal(market=market, signal_at=signal_at)
    first_five = minute_bars(signal_at, 5)
    evaluator, repository, _, source = service([row], minutes=first_five)

    first = evaluator.evaluate_signals(market=market, now=signal_at + timedelta(hours=4))

    assert repository.updates == []
    assert first["data_not_mature"] >= 2

    next_open = datetime(2026, 7, 1, 9, 30, tzinfo=local)
    source.bars = first_five + minute_bars(next_open, 60)
    second = evaluator.evaluate_signals(market=market, now=next_open + timedelta(hours=8))

    saved = repository.updates[-1][1]
    assert "30m" in saved and "1h" in saved
    assert second["30m_added"] == 1
    assert second["1h_added"] == 1


def test_daily_data_remains_missing_then_is_backfilled_on_a_later_run():
    row = make_signal(evaluation=build_initial_evaluation(supports_intraday=False))
    evaluator, repository, stocks, _ = service([row])
    now = datetime(2026, 7, 10, tzinfo=UTC)

    evaluator.evaluate_signals(market="CN", now=now)
    assert repository.updates == []

    stocks.bars = daily_bars(7)
    result = evaluator.evaluate_signals(market="CN", now=now + timedelta(hours=1))

    assert {"1d", "3d", "7d"}.issubset(repository.updates[-1][1])
    assert result["updated_signals"] == 1
