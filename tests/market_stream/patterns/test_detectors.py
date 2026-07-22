from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finance_analysis.integrations.market_data.realtime_state.models import CandleState
from finance_analysis.market_stream.patterns.breakout_retest import detect_breakout_retests
from finance_analysis.market_stream.patterns.compression import detect_compressions
from finance_analysis.market_stream.patterns.config import PatternConfig
from finance_analysis.market_stream.patterns.detector import detect_pattern_signals
from finance_analysis.market_stream.patterns.double_top_bottom import detect_double_patterns
from finance_analysis.market_stream.patterns.failed_breakout import detect_failed_breakouts
from finance_analysis.market_stream.patterns.features import PatternContext, prepare_context
from finance_analysis.market_stream.patterns.impulse_pullback import detect_impulse_pullbacks
from finance_analysis.market_stream.patterns.models import PatternSignal
from finance_analysis.market_stream.patterns.vwap import detect_vwap_patterns

START = datetime(2026, 7, 22, 14, 30, tzinfo=timezone.utc)
CONFIG = PatternConfig()
Detector = Callable[[PatternContext], list[PatternSignal]]


def candle(
    index: int,
    values: tuple[float, float, float, float],
    *,
    volume: int = 1000,
    turnover: Decimal | None | object = ...,
) -> CandleState:
    bar_time = START + timedelta(minutes=index)
    open_, high, low, close = (Decimal(str(value)) for value in values)
    if turnover is ...:
        turnover = (high + low + close) / Decimal("3") * Decimal(volume)
    return CandleState(
        symbol="SPY.US",
        bar_time=bar_time,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        turnover=turnover,  # type: ignore[arg-type]
        trade_session="Intraday",
        confirmed=True,
        received_at=bar_time + timedelta(minutes=1),
    )


def baseline(*, price: float = 100, count: int = 15) -> list[CandleState]:
    return [
        candle(index, (price, price + 0.5, price - 0.5, price + (0.1 if index % 2 else -0.1))) for index in range(count)
    ]


def append(bars: list[CandleState], values: list[tuple[float, float, float, float]]) -> list[CandleState]:
    for item in values:
        bars.append(candle(len(bars), item))
    return bars


def context(bars: list[CandleState]) -> PatternContext:
    result = prepare_context(bars, market_type="US", config=CONFIG)
    assert result is not None
    return result


def find(signals: list[PatternSignal], direction: str) -> PatternSignal:
    return next(signal for signal in signals if signal.direction == direction)


@pytest.mark.parametrize(
    ("bullish", "confirmed", "expected_direction", "expected_stage"),
    [
        (True, False, "bearish_to_bullish", "warning"),
        (True, True, "bearish_to_bullish", "confirmed"),
        (False, False, "bullish_to_bearish", "warning"),
        (False, True, "bullish_to_bearish", "confirmed"),
    ],
)
def test_failed_breakout_bull_bear_warning_and_confirmation(
    bullish: bool,
    confirmed: bool,
    expected_direction: str,
    expected_stage: str,
) -> None:
    sequence = (
        [(99.8, 100, 98.8, 99.2), (99.3, 100.1, 99.2, 99.8)]
        if bullish
        else [(100.2, 101.2, 100, 100.8), (100.7, 100.8, 99.9, 100.2)]
    )
    if confirmed:
        sequence.append((99.9, 100.5, 99.8, 100.3) if bullish else (100.1, 100.2, 99.5, 99.7))
    signal = find(detect_failed_breakouts(context(append(baseline(), sequence))), expected_direction)
    assert signal.stage == expected_stage
    assert signal.reference_level is not None
    assert signal.invalidation_price is not None


def test_failed_breakout_invalidation_near_miss_and_insufficient_data() -> None:
    invalid = append(
        baseline(),
        [(100.2, 101.2, 100, 100.8), (100.7, 100.8, 99.9, 100.2), (100.3, 101.0, 100.2, 100.8)],
    )
    near = append(baseline(), [(100.2, 100.55, 100, 100.4), (100.3, 100.4, 99.9, 100.2)])
    assert not detect_failed_breakouts(context(invalid))
    assert not detect_failed_breakouts(context(near))
    assert detect_pattern_signals(baseline(count=5), market_type="US") == []


@pytest.mark.parametrize(
    ("bullish", "confirmed", "direction", "stage"),
    [
        (True, False, "bullish_continuation", "warning"),
        (True, True, "bullish_continuation", "confirmed"),
        (False, False, "bearish_continuation", "warning"),
        (False, True, "bearish_continuation", "confirmed"),
    ],
)
def test_breakout_retest_bull_bear_warning_and_confirmation(
    bullish: bool,
    confirmed: bool,
    direction: str,
    stage: str,
) -> None:
    sequence = [(100.2, 101.1, 100.1, 100.8)] if bullish else [(99.8, 99.9, 98.9, 99.2)]
    if confirmed:
        sequence.extend(
            [(100.7, 100.8, 100.4, 100.6), (100.7, 101.3, 100.6, 101.2)]
            if bullish
            else [(99.3, 99.6, 99.2, 99.4), (99.3, 99.4, 98.7, 98.8)]
        )
    signal = find(detect_breakout_retests(context(append(baseline(), sequence))), direction)
    assert signal.stage == stage


def test_breakout_retest_invalidates_and_rejects_small_breakout() -> None:
    invalid = append(
        baseline(),
        [(100.2, 101.1, 100.1, 100.8), (100.4, 100.5, 100.0, 100.1), (100.1, 100.2, 99.8, 100.0)],
    )
    near = append(baseline(), [(100.2, 100.7, 100.1, 100.6)])
    assert not detect_breakout_retests(context(invalid))
    assert not detect_breakout_retests(context(near))


def double_sequence(*, bullish: bool, confirmed: bool) -> list[tuple[float, float, float, float]]:
    values = (
        [
            (99.5, 99.8, 98.8, 99.2),
            (99.3, 100.4, 99.2, 100.2),
            (100.1, 100.8, 99.9, 100.5),
            (100.4, 100.5, 99.3, 99.6),
            (99.5, 99.8, 98.9, 99.4),
            (99.5, 100.0, 99.4, 99.8),
        ]
        if bullish
        else [
            (100.5, 101.2, 100.2, 100.8),
            (100.7, 100.8, 99.6, 99.8),
            (99.9, 100.1, 99.2, 99.5),
            (99.6, 100.7, 99.5, 100.4),
            (100.5, 101.1, 100.2, 100.6),
            (100.5, 100.6, 100.0, 100.2),
        ]
    )
    if confirmed:
        values.append((99.9, 101.1, 99.8, 101.0) if bullish else (100.1, 100.2, 98.9, 99.0))
    return values


@pytest.mark.parametrize(
    ("bullish", "confirmed", "direction", "stage"),
    [
        (True, False, "bearish_to_bullish", "warning"),
        (True, True, "bearish_to_bullish", "confirmed"),
        (False, False, "bullish_to_bearish", "warning"),
        (False, True, "bullish_to_bearish", "confirmed"),
    ],
)
def test_double_bottom_top_requires_second_test_and_neckline_break(
    bullish: bool,
    confirmed: bool,
    direction: str,
    stage: str,
) -> None:
    signal = find(
        detect_double_patterns(context(append(baseline(), double_sequence(bullish=bullish, confirmed=confirmed)))),
        direction,
    )
    assert signal.stage == stage
    assert "微型双" in signal.pattern_name


def test_double_pattern_invalidates_and_rejects_flat_noise() -> None:
    invalid = append(baseline(), [*double_sequence(bullish=True, confirmed=False), (99.0, 99.1, 98.2, 98.3)])
    flat = append(
        baseline(),
        [(100, 100.2, 99.8, 99.9), (100, 100.3, 99.9, 100.1), (100, 100.2, 99.8, 99.9), (100, 100.2, 99.8, 100.0)],
    )
    assert not [
        signal for signal in detect_double_patterns(context(invalid)) if signal.direction == "bearish_to_bullish"
    ]
    assert not detect_double_patterns(context(flat))


def impulse_sequence(*, bullish: bool, confirmed: bool) -> list[tuple[float, float, float, float]]:
    values = (
        [
            (99.9, 100.3, 99.8, 100.2),
            (100.3, 101.2, 100.2, 101.1),
            (101.2, 102.2, 101.1, 102.0),
            (101.9, 102.0, 101.5, 101.7),
            (101.7, 101.9, 101.3, 101.5),
        ]
        if bullish
        else [
            (100.1, 100.2, 99.7, 99.8),
            (99.7, 99.8, 98.8, 98.9),
            (98.8, 98.9, 97.8, 98.0),
            (98.1, 98.5, 98.0, 98.3),
            (98.3, 98.7, 98.2, 98.5),
        ]
    )
    if confirmed:
        values.append((101.6, 102.3, 101.5, 102.2) if bullish else (98.4, 98.5, 97.7, 97.8))
    return values


@pytest.mark.parametrize(
    ("bullish", "confirmed", "direction", "stage"),
    [
        (True, False, "bullish_continuation", "forming"),
        (True, True, "bullish_continuation", "confirmed"),
        (False, False, "bearish_continuation", "forming"),
        (False, True, "bearish_continuation", "confirmed"),
    ],
)
def test_impulse_pullback_bull_bear_forming_and_confirmation(
    bullish: bool,
    confirmed: bool,
    direction: str,
    stage: str,
) -> None:
    signal = find(
        detect_impulse_pullbacks(context(append(baseline(), impulse_sequence(bullish=bullish, confirmed=confirmed)))),
        direction,
    )
    assert signal.stage == stage


def test_impulse_pullback_invalidates_and_rejects_weak_impulse() -> None:
    broken = append(baseline(), [*impulse_sequence(bullish=True, confirmed=False)[:3], (101.8, 101.9, 99.4, 99.6)])
    weak = append(
        baseline(),
        [
            (100, 100.4, 99.9, 100.3),
            (100.3, 100.8, 100.2, 100.6),
            (100.6, 100.7, 100.3, 100.4),
            (100.4, 100.6, 100.3, 100.5),
        ],
    )
    assert not detect_impulse_pullbacks(context(broken))
    assert not detect_impulse_pullbacks(context(weak))


def compression_sequence(*, bullish: bool, confirmed: bool) -> list[tuple[float, float, float, float]]:
    compact = [
        (100, 100.2, 99.8, 100.05),
        (100.05, 100.2, 99.85, 100),
        (100, 100.18, 99.88, 100.04),
        (100.04, 100.17, 99.9, 100.02),
    ]
    if confirmed:
        compact.extend(
            [(100, 100.9, 99.95, 100.8), (100.75, 101.0, 100.65, 100.9)]
            if bullish
            else [(100, 100.05, 99.1, 99.2), (99.25, 99.35, 99.0, 99.1)]
        )
    return compact


@pytest.mark.parametrize(
    ("bullish", "confirmed", "direction", "stage"),
    [
        (True, False, "neutral_wait", "forming"),
        (True, True, "bullish_breakout", "confirmed"),
        (False, False, "neutral_wait", "forming"),
        (False, True, "bearish_breakout", "confirmed"),
    ],
)
def test_compression_forming_and_held_expansion(
    bullish: bool,
    confirmed: bool,
    direction: str,
    stage: str,
) -> None:
    signal = find(
        detect_compressions(context(append(baseline(), compression_sequence(bullish=bullish, confirmed=confirmed)))),
        direction,
    )
    assert signal.stage == stage


def test_compression_failed_breakout_and_non_compression_do_not_trigger() -> None:
    failed = append(
        baseline(),
        [
            *compression_sequence(bullish=True, confirmed=False),
            (100, 100.9, 99.95, 100.8),
            (100.7, 100.75, 100.0, 100.1),
        ],
    )
    wide = append(
        baseline(),
        [(100, 100.8, 99.2, 100.4), (100.4, 101.0, 99.4, 99.7), (99.7, 100.7, 99.1, 100.2), (100.2, 100.9, 99.3, 99.8)],
    )
    assert not [signal for signal in detect_compressions(context(failed)) if signal.direction != "neutral_wait"]
    assert not detect_compressions(context(wide))


def vwap_bars(*, bullish: bool, confirmed: bool) -> list[CandleState]:
    bars: list[CandleState] = []
    first, recent = (102, 100) if bullish else (98, 100)
    for _ in range(7):
        bars.append(candle(len(bars), (first, first + 0.5, first - 0.5, first)))
    for _ in range(8):
        bars.append(candle(len(bars), (recent, recent + 0.4, recent - 0.4, recent)))
    cross = (100.2, 101.8, 100.1, 101.5) if bullish else (99.8, 99.9, 98.2, 98.5)
    bars.append(candle(len(bars), cross))
    if confirmed:
        append(
            bars,
            (
                [(101.4, 101.5, 100.7, 100.9), (100.9, 101.8, 100.8, 101.7)]
                if bullish
                else [(98.6, 99.3, 98.5, 99.1), (99.1, 99.2, 98.1, 98.3)]
            ),
        )
    return bars


@pytest.mark.parametrize(
    ("bullish", "confirmed", "direction", "stage"),
    [
        (True, False, "bearish_to_bullish", "warning"),
        (True, True, "bearish_to_bullish", "confirmed"),
        (False, False, "bullish_to_bearish", "warning"),
        (False, True, "bullish_to_bearish", "confirmed"),
    ],
)
def test_vwap_reclaim_breakdown_bull_bear_warning_and_confirmation(
    bullish: bool,
    confirmed: bool,
    direction: str,
    stage: str,
) -> None:
    signal = find(detect_vwap_patterns(context(vwap_bars(bullish=bullish, confirmed=confirmed))), direction)
    assert signal.stage == stage


def test_vwap_invalidates_and_small_cross_does_not_trigger() -> None:
    invalid = vwap_bars(bullish=True, confirmed=False)
    append(invalid, [(101.3, 101.4, 100.3, 100.4), (100.4, 100.5, 99.9, 100.0)])
    near = vwap_bars(bullish=True, confirmed=False)
    near[-1] = candle(len(near) - 1, (100.2, 101.2, 100.1, 101.0))
    assert not detect_vwap_patterns(context(invalid))
    assert not detect_vwap_patterns(context(near))
