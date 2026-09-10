from __future__ import annotations

from datetime import date, timedelta

from finance_analysis.trend_following.duration import count_trend_duration_days  # pragma: allowlist secret
from finance_analysis.trend_following.features import calculate_features  # pragma: allowlist secret
from finance_analysis.trend_following.models import DailyBar  # pragma: allowlist secret


TRADE_DATE = date(2026, 8, 28)


def _bars(closes: list[float]) -> list[DailyBar]:
    count = len(closes)
    return [
        DailyBar(
            TRADE_DATE - timedelta(days=count - index - 1),
            close - 0.5,
            close + 1.0,
            close - 1.0,
            close,
            1_000 + index * 10,
        )
        for index, close in enumerate(closes)
    ]


def _duration(closes: list[float]) -> int:
    history = _bars(closes)
    return count_trend_duration_days(history, as_of=history[-1].trade_date)


def test_trend_duration_counts_consecutive_trend_candidate_days() -> None:
    closes = [100.0 + index for index in range(23)]
    history = _bars(closes)
    features = calculate_features(history)
    assert features is not None
    assert features["trend_candidate"] is True
    assert count_trend_duration_days(history, as_of=history[-1].trade_date) == 3
    assert count_trend_duration_days(history[:22], as_of=history[21].trade_date) == 2
    assert count_trend_duration_days(history[:21], as_of=history[20].trade_date) == 1


def test_trend_duration_resets_to_zero_when_candidate_breaks() -> None:
    history = _bars([100.0 + index for index in range(23)] + [40.0])
    features = calculate_features(history)
    assert features is not None
    assert features["trend_candidate"] is False
    assert count_trend_duration_days(history, as_of=history[-1].trade_date) == 0


def test_trend_duration_restarts_at_one_after_a_break() -> None:
    closes = [100.0 + index for index in range(23)] + [40.0]
    recovery: list[float] = []
    restarted = None
    for extra in range(1, 50):
        recovery.append(40.0 + extra * 3.0)
        duration = _duration(closes + recovery)
        if duration:
            restarted = extra
            assert duration == 1
            assert _duration(closes + recovery + [recovery[-1] + 3.0]) == 2
            break
    assert restarted is not None


def test_trend_duration_is_repeatable_and_ignores_future_bars() -> None:
    history = _bars([100.0 + index for index in range(30)])
    as_of = history[22].trade_date
    first = count_trend_duration_days(history[:23], as_of=as_of)
    rerun = count_trend_duration_days(history[:23], as_of=as_of)
    with_future = count_trend_duration_days(history, as_of=as_of)
    assert first == 3
    assert first == rerun == with_future
    assert count_trend_duration_days(history[:22], as_of=as_of) == 0
