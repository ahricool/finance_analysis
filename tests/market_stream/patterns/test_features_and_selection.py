from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finance_analysis.integrations.market_data.realtime_state.models import QuoteState
from finance_analysis.market_stream.patterns.config import PatternConfig
from finance_analysis.market_stream.patterns.detector import (
    calculate_pattern_state,
    detect_pattern_signals,
    select_primary_pattern,
)
from finance_analysis.market_stream.patterns.features import (
    adjacent_overlap,
    body_ratio,
    candle_body,
    direction_efficiency,
    lower_wick,
    median_body,
    median_volume,
    normalized_distance,
    prepare_preview_bars,
    range_width,
    robust_atr,
    rolling_high,
    rolling_low,
    sanitize_bars,
    session_minutes_between,
    session_vwap,
    true_range,
    upper_wick,
    volume_ratio,
)
from finance_analysis.market_stream.patterns.models import PatternSignal, PatternState
from tests.market_stream.patterns.test_detectors import START, append, baseline, candle


def signal(
    *,
    pattern_type: str = "vwap_reclaim_breakdown",
    direction: str = "bearish_to_bullish",
    stage: str = "warning",
    score: int = 70,
    bars_ago: int = 0,
    minute: int = 20,
) -> PatternSignal:
    occurred = START + timedelta(minutes=minute)
    confirmed_at = occurred if stage == "confirmed" else None
    return PatternSignal(
        symbol="SPY.US",
        pattern_type=pattern_type,  # type: ignore[arg-type]
        pattern_name="测试形态",
        direction=direction,  # type: ignore[arg-type]
        stage=stage,  # type: ignore[arg-type]
        quality_score=score,
        occurred_at=occurred,
        confirmed_at=confirmed_at,
        trading_date=date(2026, 7, 22),
        trade_session="Intraday",
        bars_ago=bars_ago,
        session_minutes_ago=bars_ago,
        reference_level=Decimal("100"),
        invalidation_price=Decimal("99"),
        reasons=("确定性测试",),
        confirmed=stage == "confirmed",
    )


def test_sanitize_uses_only_latest_date_confirmed_regular_bars_and_deduplicates() -> None:
    current = baseline(count=3)
    duplicate = replace(current[1], close=Decimal("100.2"), received_at=current[1].received_at + timedelta(seconds=5))
    previous = replace(current[0], bar_time=current[0].bar_time - timedelta(days=1))
    unconfirmed = replace(current[-1], bar_time=current[-1].bar_time + timedelta(minutes=1), confirmed=False)
    premarket = replace(current[0], bar_time=current[0].bar_time.replace(hour=12))
    postmarket = replace(current[0], bar_time=current[0].bar_time + timedelta(hours=8), trade_session="Post")

    result = sanitize_bars(
        [postmarket, current[2], previous, current[1], unconfirmed, premarket, duplicate, current[0]], "US"
    )

    assert [bar.bar_time for bar in result] == [current[0].bar_time, current[1].bar_time, current[2].bar_time]
    assert result[1].close == Decimal("100.2")
    assert all(bar.confirmed for bar in result)


def test_unconfirmed_pattern_bar_cannot_change_final_state() -> None:
    bars = append(baseline(), [(100.2, 101.2, 100, 100.8), (100.7, 100.8, 99.9, 100.2)])
    warning = calculate_pattern_state(bars, market_type="US")
    bars.append(replace(candle(len(bars), (100.1, 100.2, 99.5, 99.7)), confirmed=False))

    after_unconfirmed = calculate_pattern_state(bars, market_type="US")

    assert warning.status == "active"
    assert after_unconfirmed == warning
    assert after_unconfirmed.signal is not None and after_unconfirmed.signal.stage == "warning"


def test_preview_keeps_only_latest_unconfirmed_current_day_regular_bar() -> None:
    confirmed = baseline(count=3)
    first_unconfirmed = replace(candle(3, (100, 101, 99, 100.5)), confirmed=False)
    latest_unconfirmed = replace(candle(4, (100.5, 102, 100, 101.5)), confirmed=False)
    old_unconfirmed = replace(first_unconfirmed, bar_time=first_unconfirmed.bar_time - timedelta(days=1))
    postmarket = replace(latest_unconfirmed, bar_time=latest_unconfirmed.bar_time + timedelta(hours=8), trade_session="Post")

    result = prepare_preview_bars(
        [old_unconfirmed, *confirmed, first_unconfirmed, postmarket, latest_unconfirmed],
        "US",
    )

    assert result[:-1] == confirmed
    assert result[-1] == latest_unconfirmed
    assert sum(not bar.confirmed for bar in result) == 1


def test_preview_quote_updates_temporary_ohlc_without_mutating_source() -> None:
    unfinished = replace(candle(15, (100, 101, 99, 100)), confirmed=False)
    quote = QuoteState(symbol=unfinished.symbol)
    quote_time = unfinished.bar_time + timedelta(seconds=30)
    quote.merge(
        {"last_price": "102", "trade_session": "Intraday"},
        event_time=quote_time,
        received_at=unfinished.received_at + timedelta(seconds=1),
        trading_date=date(2026, 7, 22),
    )

    prepared = prepare_preview_bars([*baseline(), unfinished], "US", quote=quote)

    assert prepared[-1].close == Decimal("102")
    assert prepared[-1].high == Decimal("102")
    assert prepared[-1].low == Decimal("99")
    assert unfinished.close == Decimal("100")
    assert unfinished.high == Decimal("101")
    assert unfinished.low == Decimal("99")


@pytest.mark.parametrize("change", ["minute", "date", "stale", "symbol", "session"])
def test_preview_rejects_quote_from_other_minute_date_or_older_data(change: str) -> None:
    unfinished = replace(candle(15, (100, 101, 99, 100)), confirmed=False)
    event_time = unfinished.bar_time + timedelta(seconds=20)
    received_at = unfinished.received_at + timedelta(seconds=1)
    trading_date = date(2026, 7, 22)
    if change == "minute":
        event_time += timedelta(minutes=1)
    elif change == "date":
        trading_date -= timedelta(days=1)
    elif change == "stale":
        received_at = unfinished.received_at
    symbol = "QQQ.US" if change == "symbol" else unfinished.symbol
    trade_session = "Post" if change == "session" else "Intraday"
    quote = QuoteState(symbol=symbol)
    quote.merge(
        {"last_price": "102", "trade_session": trade_session},
        event_time=event_time,
        received_at=received_at,
        trading_date=trading_date,
    )

    assert prepare_preview_bars([*baseline(), unfinished], "US", quote=quote)[-1].close == unfinished.close


def test_confirmed_preview_signal_is_downgraded_without_changing_formal_signal(monkeypatch) -> None:
    confirmed_signal = signal(stage="confirmed", minute=14)

    def fixed_signals(*args, **kwargs):
        return [confirmed_signal]

    monkeypatch.setattr("finance_analysis.market_stream.patterns.detector.detect_pattern_signals", fixed_signals)
    unfinished = replace(candle(15, (100, 101, 99, 100.5)), confirmed=False)
    state = calculate_pattern_state([*baseline(), unfinished], market_type="US", include_preview=True)

    assert state.signal is confirmed_signal
    assert state.signal.confirmed and state.signal.stage == "confirmed"
    assert state.preview_signal is not None
    assert not state.preview_signal.confirmed
    assert state.preview_signal.stage == "warning"
    assert state.preview_signal.confirmed_at is None
    assert "当前一分钟K线尚未收盘" in state.preview_signal.reasons[-1]


def test_zero_or_tiny_atr_returns_insufficient_safely() -> None:
    flat = [candle(index, (100, 100, 100, 100), volume=0, turnover=None) for index in range(20)]
    assert robust_atr(flat, 20) == 0
    state = calculate_pattern_state(flat, market_type="US")
    assert state.status == "insufficient"
    assert state.signal is None


def test_shared_decimal_features_are_stable_and_safe() -> None:
    first = candle(0, (100, 103, 99, 102), volume=1000)
    second = candle(1, (102, 104, 101, 103), volume=2000)
    assert true_range(first) == Decimal("4")
    assert true_range(second, first.close) == Decimal("3")
    assert candle_body(first) == Decimal("2")
    assert upper_wick(first) == Decimal("1")
    assert lower_wick(first) == Decimal("1")
    assert body_ratio(first) == Decimal("0.5")
    assert median_body([first, second], 2) == Decimal("1.5")
    assert median_volume([first, second], 2) == Decimal("1500")
    assert volume_ratio(second, Decimal("1000")) == Decimal("2")
    assert adjacent_overlap(first, second) == Decimal("2") / Decimal("3")
    assert range_width([first, second]) == Decimal("5")
    assert direction_efficiency([first, second]) == Decimal("1")
    assert rolling_high([first, second]) == Decimal("104")
    assert rolling_low([first, second]) == Decimal("99")
    assert normalized_distance(Decimal("103"), Decimal("102"), Decimal("2"), Decimal("0.01")) == Decimal("0.5")


def test_vwap_uses_turnover_when_reasonable_and_falls_back_when_missing_or_abnormal() -> None:
    bars = [
        candle(0, (100, 101, 99, 100), volume=0, turnover=None),
        candle(1, (100, 102, 99, 101), volume=100, turnover=None),
        candle(2, (101, 103, 100, 102), volume=100, turnover=Decimal("999999")),
        candle(3, (102, 104, 101, 103), volume=100, turnover=Decimal("10300")),
    ]
    values = session_vwap(bars, atr=Decimal("1"), config=PatternConfig())
    typical_one = (Decimal("102") + Decimal("99") + Decimal("101")) / Decimal("3")
    typical_two = (Decimal("103") + Decimal("100") + Decimal("102")) / Decimal("3")

    assert values[0] is None
    assert values[1] == typical_one
    assert values[2] == (typical_one + typical_two) / Decimal("2")
    assert values[3] == (typical_one * 100 + typical_two * 100 + Decimal("10300")) / Decimal("300")


def test_session_minutes_exclude_cn_lunch_break_and_track_missing_bars() -> None:
    morning_time = datetime(2026, 7, 22, 3, 29, tzinfo=timezone.utc)
    afternoon_time = datetime(2026, 7, 22, 5, 0, tzinfo=timezone.utc)
    morning = replace(candle(0, (100, 101, 99, 100)), bar_time=morning_time)
    afternoon = replace(candle(1, (100, 101, 99, 100)), bar_time=afternoon_time)

    assert session_minutes_between(morning, afternoon, "CN") == 1
    assert (
        session_minutes_between(morning, replace(afternoon, bar_time=afternoon_time + timedelta(minutes=5)), "CN") == 6
    )


def test_primary_selection_orders_stage_recency_score_then_pattern_priority_stably() -> None:
    latest = START + timedelta(minutes=40)
    confirmed_old = signal(stage="confirmed", bars_ago=8, score=50, minute=10)
    warning_new = signal(stage="warning", bars_ago=0, score=99, minute=40)
    assert select_primary_pattern([warning_new, confirmed_old], latest_bar_time=latest) == confirmed_old

    recent = signal(stage="confirmed", bars_ago=1, score=50, minute=39)
    high_score_old = signal(stage="confirmed", bars_ago=2, score=95, minute=38)
    assert select_primary_pattern([high_score_old, recent], latest_bar_time=latest) == recent

    failed = signal(
        pattern_type="failed_breakout_reclaim",
        stage="confirmed",
        bars_ago=1,
        score=80,
        minute=39,
    )
    vwap = signal(stage="confirmed", bars_ago=1, score=80, minute=39)
    assert select_primary_pattern([vwap, failed], latest_bar_time=latest) == failed
    assert select_primary_pattern([failed, vwap], latest_bar_time=latest) == failed


def test_confirmed_failed_breakout_suppresses_overlapping_ordinary_breakout() -> None:
    bars = append(
        baseline(),
        [(100.2, 101.2, 100, 100.8), (100.7, 100.8, 99.9, 100.2), (100.1, 100.2, 99.5, 99.7)],
    )
    signals = detect_pattern_signals(bars, market_type="US")
    assert any(signal.pattern_type == "failed_breakout_reclaim" and signal.confirmed for signal in signals)
    assert not any(
        signal.pattern_type in {"breakout_retest_continuation", "compression_expansion"}
        and signal.direction in {"bullish_continuation", "bullish_breakout"}
        for signal in signals
    )


def test_patterns_older_than_maximum_age_are_not_selected() -> None:
    old = signal(stage="confirmed", bars_ago=16, minute=10)
    assert select_primary_pattern([old], latest_bar_time=START + timedelta(minutes=40)) is None


def test_quality_score_bounds_and_state_round_trip() -> None:
    original_signal = signal(stage="confirmed", score=100)
    preview_signal = replace(original_signal, stage="warning", confirmed=False, confirmed_at=None)
    state = PatternState(
        symbol="SPY.US",
        status="active",
        signal=original_signal,
        trading_date=date(2026, 7, 22),
        bar_time=START + timedelta(minutes=20),
        preview_status="active",
        preview_signal=preview_signal,
        preview_bar_time=START + timedelta(minutes=21),
        preview_price=Decimal("101.25"),
        preview_updated_at=START + timedelta(minutes=21, seconds=20),
    )
    restored = PatternState.from_mapping(state.to_mapping())
    assert restored == state
    assert restored.signal is not None
    assert 0 <= restored.signal.quality_score <= 100


def test_old_pattern_mapping_without_preview_fields_uses_safe_defaults() -> None:
    mapping = PatternState(symbol="SPY.US", status="none").to_mapping()
    for key in ["preview_status", "preview_signal", "preview_bar_time", "preview_price", "preview_updated_at"]:
        mapping.pop(key)

    restored = PatternState.from_mapping(mapping)

    assert restored.preview_status == "insufficient"
    assert restored.preview_signal is None
    assert restored.preview_bar_time is None


def test_calculate_state_distinguishes_insufficient_none_and_active() -> None:
    insufficient = calculate_pattern_state(baseline(count=5), market_type="US")
    none = calculate_pattern_state(baseline(count=20), market_type="US")
    active = calculate_pattern_state(
        append(baseline(), [(100.2, 101.2, 100, 100.8), (100.7, 100.8, 99.9, 100.2)]),
        market_type="US",
    )
    assert insufficient.status == "insufficient"
    assert none.status == "none"
    assert active.status == "active"
