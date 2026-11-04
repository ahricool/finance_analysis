"""Independent Entry episodes: shallow support, PIT resistance and preserved quality."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta

import pytest

from finance_analysis.trend_following.config import TrendFollowingConfig
from finance_analysis.trend_following.entry import calculate_entry
from finance_analysis.trend_following.entry_setups import entry_context
from finance_analysis.trend_following.features import calculate_features
from finance_analysis.trend_following.models import DailyBar
from finance_analysis.trend_following.ranking import rank_candidates


def advance():
    return [
        DailyBar(
            date(2026, 1, 1) + timedelta(days=i), 100 + 0.4 * i, 100.6 + 0.4 * i, 99.4 + 0.4 * i, 100 + 0.4 * i, 1000
        )
        for i in range(100)
    ]


def shallow(close=140, low=138.75, opened=139.4, high=None):
    history = advance()
    return history + [
        DailyBar(history[-1].trade_date + timedelta(days=1), opened, high or max(close, opened) + 0.2, low, close, 1000)
    ]


def evaluate(series, period=20, **updates):
    config = TrendFollowingConfig(trend_period=period)
    features = calculate_features(series, config=config)
    features.update(code="AAA.US", rs_5d=0.08, rs_10d=0.12, rs_20d=0.18)
    row = rank_candidates([features], config)[0]
    row.update(updates)
    return calculate_entry(row, config, bars=series), row


@pytest.mark.parametrize("period", [10, 20, 40])
def test_ma5_shallow_intraday_reclaim_survives_alpha_drop_and_uses_fixed_execution_ma(period):
    series = shallow()
    result, row = evaluate(series, period, alpha_score=40, rs_score=40, trend_score=40)
    assert series[-2].close > row["previous_ma10"]  # Yesterday never closed below the MA.
    assert result["entry_ma5_status"] == "CONFIRMED"
    assert result["entry_ma10_status"] == "WAITING_PULLBACK"
    assert result["entry_retest_score"] is None  # No known breakout support: no invented shape score.
    assert result["entry_execution_ma5"] == pytest.approx(138.8)
    assert result["entry_execution_ma10"] == pytest.approx(137.8)
    assert result["entry_type"] == "PULLBACK_RESUME" and result["entry_ma5_score"] > 0
    assert "alpha_score" not in result["entry_breakdown"]["pullbacks"]["ma5"]["checks"]


def test_ma10_recovery_is_independent_of_failed_ma5_support():
    result, _ = evaluate(shallow(close=139.2, low=137.75, opened=138.4))
    assert result["entry_ma5_status"] == "INVALIDATED"
    assert result["entry_ma10_status"] == "CONFIRMED"
    assert result["entry_type"] == "PULLBACK_RESUME"


def test_single_touch_waits_for_actual_recovery_and_keeps_quality():
    result, _ = evaluate(shallow(close=139.3, low=138.75, opened=139.6, high=139.9))
    assert result["entry_ma5_status"] == "PULLING_BACK"
    assert result["entry_ma5_score"] > 0 and result["entry_type"] == "NONE"


def test_no_prior_uptrend_cannot_become_pullback_from_touch_alone():
    series = [replace(b, open=100, high=100.6, low=99.4, close=100) for b in advance()]
    series.append(DailyBar(series[-1].trade_date + timedelta(days=1), 100, 101.2, 99.9, 101, 1000))
    result, _ = evaluate(series)
    assert result["entry_ma5_status"] == "WAITING_PULLBACK"
    assert result["entry_ma10_status"] == "WAITING_PULLBACK"


def test_structural_failure_preserves_quality_and_cannot_confirm():
    result, _ = evaluate(shallow(close=132, low=130, opened=133))
    assert result["entry_ma5_status"] == "INVALIDATED"
    assert result["entry_ma10_status"] == "INVALIDATED"
    assert result["entry_ma5_score"] > 0 and result["entry_type"] == "NONE"


def test_breakout_and_shallow_pullback_can_confirm_together_without_overwriting_results():
    result, _ = evaluate(shallow(close=140.7), alpha_score=90, trend_score=90, rs_score=90, path_score=90)
    assert result["entry_breakout_status"] == "CONFIRMED"
    assert result["entry_ma5_status"] == "CONFIRMED"
    assert result["entry_type"] == "BREAKOUT_AND_PULLBACK"
    assert result["entry_breakout_score"] > 0 and result["entry_ma5_score"] > 0


def test_overextended_recovery_has_its_own_status_and_quality():
    result, _ = evaluate(shallow(close=142))
    assert result["entry_ma5_status"] == "EXTENDED" and result["entry_ma5_score"] > 0


def test_retest_uses_resistance_known_before_historical_breakout():
    series = advance()
    known_level = max(b.high for b in series[-20:])
    for opened, high, low, close in [
        (140, 141.3, 139.8, 141.2),
        (141.3, 142.7, 141, 142.5),
        (140.8, 141.9, known_level - 0.1, 141.8),
    ]:
        series.append(DailyBar(series[-1].trade_date + timedelta(days=1), opened, high, low, close, 1000))
    result, _ = evaluate(series)
    evidence = result["entry_breakdown"]["pullbacks"]["retest"]["evidence"]
    assert result["entry_retest_status"] == "CONFIRMED"
    assert evidence["breakout_level"] == pytest.approx(known_level)
    assert evidence["breakout_date"] == series[-3].trade_date.isoformat()
    assert evidence["touch_date"] > evidence["breakout_date"]
    # Today's changing high can affect recovery quality, but cannot rewrite the known resistance.
    series[-1] = replace(series[-1], high=999)
    assert entry_context(series)["pullbacks"]["retest"]["breakout_level"] == pytest.approx(known_level)


def test_insufficient_history_and_missing_window_session_never_assume_eligibility():
    series = shallow()
    assert not entry_context(series[-21:])["history_ready"]
    assert entry_context(series[-21:])["pullbacks"]["ma5"]["status"] != "CONFIRMED"
    missing = series[:-5] + series[-4:]
    context = entry_context(missing, sessions=[b.trade_date for b in series[-11:]])
    assert not context["history_ready"] and context["pullbacks"]["ma5"]["status"] != "CONFIRMED"


def test_entry_is_pure_and_reproducible_from_frozen_context():
    series = shallow()
    result, row = evaluate(series, alpha_score=40)
    original = deepcopy(row)
    replay = calculate_entry({**row, **result})
    assert replay == result
    assert row == original
    assert TrendFollowingConfig().history_bars >= 22


def test_earliest_window_pullback_can_use_the_already_known_prior_advance():
    series = shallow()[:-1]
    # This bar will be exactly ten sessions before the evaluation day.
    index = len(series) - 10
    support = sum(b.close for b in series[index - 5 : index]) / 5
    series[index] = replace(series[index], low=support - 0.05)
    context = entry_context(series)
    assert context["pullbacks"]["ma5"]["touch_date"] == series[index].trade_date.isoformat()
    assert context["pullbacks"]["ma5"]["advanced_date"] < context["pullbacks"]["ma5"]["touch_date"]


@pytest.mark.parametrize("offset,expected", [(0.25, "CONFIRMED"), (0.25001, "WAITING_PULLBACK")])
def test_atr_touch_tolerance_boundary(offset, expected):
    result, _ = evaluate(shallow(low=138.8 + offset * 1.2))
    assert result["entry_ma5_status"] == expected


def test_failed_breakout_level_cannot_recover_by_arming_the_advance_later():
    series = advance()
    for opened, high, low, close in [
        (140.25, 140.6, 140.1, 140.5),
        (140.4, 140.4, 138.8, 140),
        (140.5, 142.5, 140.4, 141),
        (140.3, 141.3, 140.2, 141.1),
    ]:
        series.append(DailyBar(series[-1].trade_date + timedelta(days=1), opened, high, low, close, 1000))
    context = entry_context(series)
    assert context["pullbacks"]["retest"]["status"] == "INVALIDATED"
    assert context["pullbacks"]["retest"]["support_intact"] is False


@pytest.mark.parametrize("period", [10, 20, 40])
def test_official_and_preview_share_entry_logic_with_real_session_warmup(monkeypatch, period):
    from tests.test_trend_following_service import FakeRepository, TrendFollowingService, TRADE_DATE
    from finance_analysis.market_review.trading_calendar import get_trading_days_between
    from finance_analysis.trend_following.models import UniverseMember

    sessions = get_trading_days_between("us", TRADE_DATE - timedelta(days=300), TRADE_DATE)[-101:]
    series = [replace(b, trade_date=day) for b, day in zip(shallow(), sessions)]

    class Repository(FakeRepository):
        def load_daily_history(self, codes, trade_date, *, calendar_lookback_days):
            return [
                dict(
                    instrument_id=index,
                    code=code,
                    name=code,
                    trade_date=b.trade_date,
                    open=b.open,
                    high=b.high,
                    low=b.low,
                    close=b.close,
                    volume=b.volume,
                    amount=None,
                )
                for index, code in enumerate(("AAA.US", "BBB.US", "SPY.US"), 1)
                for b in series
            ]

    repository = Repository()
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",
        lambda market: (UniverseMember("US", "AAA.US", "AAA"), UniverseMember("US", "BBB.US", "BBB")),
    )
    config = TrendFollowingConfig(trend_period=period)
    service = TrendFollowingService("US", repository, config=config)
    assert service.run(TRADE_DATE)["status"] == "completed"
    official = deepcopy(repository.snapshots)
    preview = service._run_single_date(
        TRADE_DATE, persist=False, overlay_bars={code: series[-1] for code in ("AAA.US", "BBB.US", "SPY.US")}
    )
    assert preview["status"] == "completed"
    for first, second in zip(official, preview["snapshots"]):
        assert first["features"]["entry_ma5_status"] == second["features"]["entry_ma5_status"] == "CONFIRMED"
        assert first["features"]["entry_context"] == second["features"]["entry_context"]
        assert first["features"]["entry_context"]["history_ready"]
        assert first["features"]["entry_execution_ma5"] == pytest.approx(138.8)
    assert repository.snapshots == official  # Preview did not replace the saved formal batch.


def test_short_horizon_breakout_level_is_available_even_without_long_horizon_breakout():
    series = advance()
    series[-15] = replace(series[-15], high=150)
    level = max(b.high for b in series[-10:])
    for opened, high, low, close in [
        (140, 141.3, 139.8, 141.2),
        (141.3, 142.7, 141, 142.5),
        (140.8, 141.9, level - 0.1, 141.8),
    ]:
        series.append(DailyBar(series[-1].trade_date + timedelta(days=1), opened, high, low, close, 1000))
    context = entry_context(series)
    retest = context["pullbacks"]["retest"]
    assert retest["status"] == "CONFIRMED"
    assert retest["breakout_window"] == 10 and retest["breakout_level"] == pytest.approx(level)
