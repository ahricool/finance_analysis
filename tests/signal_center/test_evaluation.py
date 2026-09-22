from copy import deepcopy
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from finance_analysis.signal_center.evaluation import calculate, session_plan, with_evaluations


def signal(market="US", day="2026-09-18", completed="2026-09-19T03:20:00+00:00"):
    return dict(
        market=market,
        signal_date=day,
        completed_at=completed,
        status="completed",
        decision="BUY",
        selected_symbol="TEST.US" if market == "US" else "600000.SH",
    )


def bar(day, close=110, high=120, low=90, op=100, volume=1):
    return dict(code="TEST.US", date=day, open=op, high=high, low=low, close=close, volume=volume)


def plan():
    return [(date(2026, 9, i), datetime(2026, 9, i, 20, tzinfo=timezone.utc)) for i in range(1, 11)]


def test_returns_use_entry_open_and_exact_sessions_with_drawdown():
    schedule = plan()
    bars = {day: bar(day) for day, _ in schedule}
    bars[schedule[1][0]] = bar(schedule[1][0], close=90)
    result = calculate(schedule, bars, datetime(2026, 9, 11, tzinfo=timezone.utc))
    assert result["status"] == "complete"
    assert result["entry_price"] == 100
    assert [h["value"] for h in result["horizons"]] == pytest.approx([0.1] * 4)
    assert result["mfe"] == pytest.approx(0.2)
    assert result["mae"] == pytest.approx(-0.1)
    assert result["max_drawdown_close"] == pytest.approx(90 / 110 - 1)


def test_future_bars_and_intraday_prices_are_not_used():
    schedule = plan()
    bars = {day: bar(day) for day, _ in schedule}
    result = calculate(schedule, bars, datetime(2026, 9, 3, 19, tzinfo=timezone.utc))
    assert result["observed_sessions"] == 2
    assert result["as_of"] == date(2026, 9, 2)
    assert result["horizons"][0]["value"] == pytest.approx(0.1)
    assert all(h["status"] == "pending" for h in result["horizons"][1:])


@pytest.mark.parametrize("replacement", [None, {"volume": 0}, {"close": float("nan")}, {"low": 200}])
def test_missing_or_invalid_bar_does_not_shift_horizons_or_claim_extrema(replacement):
    schedule = plan()
    bars = {day: bar(day) for day, _ in schedule}
    day = schedule[1][0]
    bars[day] = None if replacement is None else {**bars[day], **replacement}
    result = calculate(schedule, bars, datetime(2026, 9, 11, tzinfo=timezone.utc))
    assert result["status"] == "partial"
    assert result["missing_dates"] == [day]
    assert result["horizons"][0]["value"] == pytest.approx(0.1)
    assert all(h["status"] == "missing" and h["value"] is None for h in result["horizons"][1:])
    assert result["mfe"] is result["mae"] is result["max_drawdown_close"] is None


def test_missing_entry_does_not_substitute_next_available_open():
    schedule = plan()
    bars = {day: bar(day) for day, _ in schedule[1:]}
    result = calculate(schedule, bars, datetime(2026, 9, 11, tzinfo=timezone.utc))
    assert result["entry_price"] is None
    assert result["status"] == "unavailable"
    assert all(h["value"] is None for h in result["horizons"])


def test_exchange_weekends_holidays_dst_and_late_publication():
    assert session_plan(signal())[0][0] == date(2026, 9, 21)
    # Actual completion after Monday's open cannot use that morning's price.
    assert session_plan(signal(completed="2026-09-21T13:31:00+00:00"))[0][0] == date(2026, 9, 22)
    assert session_plan(signal(day="2026-03-06", completed="2026-03-07T04:20:00+00:00"))[0][1].hour == 20
    # Thanksgiving and the following early close.
    assert session_plan(signal(day="2026-11-25", completed="2026-11-26T04:20:00+00:00"))[0] == (
        date(2026, 11, 27),
        datetime(2026, 11, 27, 18, tzinfo=timezone.utc),
    )
    assert session_plan(signal("CN", "2026-09-18", "2026-09-18T13:00:00+00:00"))[0][0] == date(2026, 9, 21)


def test_batch_read_only_enrichment_and_notrade(monkeypatch):
    calls = []
    repo = SimpleNamespace(load_evaluation_bars=lambda pairs: calls.append(pairs) or [bar(d) for _, d in pairs])
    original = [signal(), signal(), {**signal(), "decision": "NO_TRADE", "selected_symbol": None}]
    before = deepcopy(original)
    rows = with_evaluations(repo, original, datetime(2026, 9, 23, 12, tzinfo=timezone.utc))
    assert original == before
    assert len(calls) == 1 and len(calls[0]) == 2
    assert rows[0]["evaluation"]["observed_sessions"] == 2
    assert rows[2]["evaluation"]["status"] == "not_applicable"
    with_evaluations(repo, [original[2]])
    assert len(calls) == 1
    monkeypatch.setattr("finance_analysis.signal_center.evaluation.calendar._XCALS_AVAILABLE", False)
    assert with_evaluations(repo, [signal()])[0]["evaluation"]["status"] == "unavailable"
    assert len(calls) == 1


def test_missing_completion_time_is_not_guessed():
    result = with_evaluations(SimpleNamespace(), [{**signal(), "completed_at": None}])
    assert result[0]["evaluation"]["status"] == "unavailable"
