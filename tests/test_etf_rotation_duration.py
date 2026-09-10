from __future__ import annotations

from datetime import date, timedelta

from finance_analysis.etf_rotation.duration import count_trend_duration_days  # pragma: allowlist secret
from finance_analysis.etf_rotation.eligibility import is_absolute_trend_eligible  # pragma: allowlist secret
from finance_analysis.etf_rotation.features import calculate_features  # pragma: allowlist secret
from finance_analysis.etf_rotation.models import DailyBar  # pragma: allowlist secret


def _bars(closes: list[float]) -> list[DailyBar]:
    return [
        DailyBar(date(2026, 1, 1) + timedelta(days=index), close, 1000, 100_000_000)
        for index, close in enumerate(closes)
    ]


def _duration(closes: list[float]) -> int:
    history = _bars(closes)
    return count_trend_duration_days(history, as_of=history[-1].trade_date)


def test_etf_duration_counts_three_consecutive_absolute_trend_days() -> None:
    closes = [100.0 + index for index in range(23)]
    history = _bars(closes)
    as_of = history[-1].trade_date
    assert is_absolute_trend_eligible(calculate_features(history).to_dict()) is True
    assert count_trend_duration_days(history, as_of=as_of) == 3
    assert count_trend_duration_days(history[:22], as_of=history[21].trade_date) == 2
    assert count_trend_duration_days(history[:21], as_of=history[20].trade_date) == 1


def test_etf_duration_resets_to_zero_when_absolute_trend_breaks() -> None:
    broken = [100.0 + index for index in range(23)] + [50.0]
    history = _bars(broken)
    assert is_absolute_trend_eligible(calculate_features(history).to_dict()) is False
    assert count_trend_duration_days(history, as_of=history[-1].trade_date) == 0


def test_etf_duration_restarts_at_one_after_a_break() -> None:
    closes = [100.0 + index for index in range(23)] + [50.0]
    recovery: list[float] = []
    restarted = None
    for extra in range(1, 40):
        recovery.append(50.0 + extra * 2.0)
        duration = _duration(closes + recovery)
        if duration:
            restarted = extra
            assert duration == 1
            assert _duration(closes + recovery + [recovery[-1] + 2.0]) == 2
            break
    assert restarted is not None


def test_etf_duration_is_repeatable_and_ignores_future_bars() -> None:
    history = _bars([100.0 + index for index in range(30)])
    as_of = history[22].trade_date
    first = count_trend_duration_days(history[:23], as_of=as_of)
    rerun = count_trend_duration_days(history[:23], as_of=as_of)
    with_future = count_trend_duration_days(history, as_of=as_of)
    assert first == 3
    assert first == rerun == with_future
    missing_as_of = count_trend_duration_days(history[:22], as_of=as_of)
    assert missing_as_of == 0


def test_etf_duration_is_not_truncated_by_strategy_history_window() -> None:
    history = _bars([100.0 + index for index in range(120)])
    as_of = history[-1].trade_date
    strategy_window = 60
    warmup = 21
    truncated = count_trend_duration_days(history[-strategy_window:], as_of=as_of)
    full = count_trend_duration_days(history, as_of=as_of)
    assert is_absolute_trend_eligible(calculate_features(history).to_dict()) is True
    assert truncated == strategy_window - warmup + 1
    assert truncated <= 40
    assert full > 40
    assert full == len(history) - warmup + 1
