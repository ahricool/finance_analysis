"""Public orchestration API and deterministic primary-signal selection."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from finance_analysis.integrations.market_data.realtime_state.models import CandleState
from finance_analysis.market_stream.config import market_trading_date
from finance_analysis.market_stream.patterns.breakout_retest import detect_breakout_retests
from finance_analysis.market_stream.patterns.compression import detect_compressions
from finance_analysis.market_stream.patterns.config import PatternConfig
from finance_analysis.market_stream.patterns.double_top_bottom import detect_double_patterns
from finance_analysis.market_stream.patterns.failed_breakout import detect_failed_breakouts
from finance_analysis.market_stream.patterns.features import prepare_context, sanitize_bars
from finance_analysis.market_stream.patterns.impulse_pullback import detect_impulse_pullbacks
from finance_analysis.market_stream.patterns.models import PatternSignal, PatternState
from finance_analysis.market_stream.patterns.vwap import detect_vwap_patterns
from finance_analysis.stocks.markets import MarketType

PATTERN_PRIORITY = {
    "failed_breakout_reclaim": 1,
    "breakout_retest_continuation": 2,
    "micro_double_bottom_top": 3,
    "impulse_pullback_resume": 4,
    "compression_expansion": 5,
    "vwap_reclaim_breakdown": 6,
}
STAGE_PRIORITY = {"confirmed": 3, "warning": 2, "forming": 1}


def detect_pattern_signals(
    bars: Sequence[CandleState],
    *,
    market_type: MarketType,
    config: PatternConfig | None = None,
) -> list[PatternSignal]:
    """Detect all currently valid candidates from confirmed current-session bars."""
    selected_config = config or PatternConfig()
    context = prepare_context(bars, market_type=market_type, config=selected_config)
    if context is None:
        return []
    failed = detect_failed_breakouts(context)
    ordinary = [
        *detect_breakout_retests(context),
        *detect_double_patterns(context),
        *detect_impulse_pullbacks(context),
        *detect_compressions(context),
        *detect_vwap_patterns(context),
    ]
    confirmed_failed = [signal for signal in failed if signal.confirmed]
    if confirmed_failed:
        ordinary = [
            signal
            for signal in ordinary
            if not any(
                _overlaps_failed_breakout(signal, failed_signal, selected_config) for failed_signal in confirmed_failed
            )
        ]
    return [*failed, *ordinary]


def select_primary_pattern(
    signals: Sequence[PatternSignal],
    *,
    latest_bar_time: datetime,
    config: PatternConfig | None = None,
) -> PatternSignal | None:
    """Choose one stable primary signal by validity, stage, recency, score, and type priority."""
    selected_config = config or PatternConfig()
    valid = [
        signal
        for signal in signals
        if signal.bars_ago <= selected_config.maximum_age_bars
        and signal.occurred_at <= latest_bar_time
        and (signal.confirmed_at is None or signal.confirmed_at <= latest_bar_time)
    ]
    if not valid:
        return None
    return max(
        valid,
        key=lambda signal: (
            STAGE_PRIORITY[signal.stage],
            -signal.bars_ago,
            signal.quality_score,
            -PATTERN_PRIORITY[signal.pattern_type],
            signal.confirmed_at or signal.occurred_at,
            signal.pattern_type,
            signal.direction,
            signal.pattern_name,
        ),
    )


def calculate_pattern_state(
    bars: Sequence[CandleState],
    *,
    market_type: MarketType,
    config: PatternConfig | None = None,
) -> PatternState:
    """Build the serializable primary state without I/O or wall-clock dependencies."""
    selected_config = config or PatternConfig()
    ordered = sanitize_bars(bars, market_type)
    symbol = ordered[-1].symbol if ordered else next((bar.symbol for bar in bars), "")
    if not ordered:
        return PatternState(symbol=symbol)
    trading_date = market_trading_date(ordered[-1].bar_time, market_type)
    if prepare_context(ordered, market_type=market_type, config=selected_config) is None:
        return PatternState(
            symbol=symbol,
            status="insufficient",
            trading_date=trading_date,
            bar_time=ordered[-1].bar_time,
        )
    signals = detect_pattern_signals(ordered, market_type=market_type, config=selected_config)
    primary = select_primary_pattern(
        signals,
        latest_bar_time=ordered[-1].bar_time,
        config=selected_config,
    )
    return PatternState(
        symbol=symbol,
        status="active" if primary else "none",
        signal=primary,
        trading_date=trading_date,
        bar_time=ordered[-1].bar_time,
    )


def _overlaps_failed_breakout(
    signal: PatternSignal,
    failed: PatternSignal,
    config: PatternConfig,
) -> bool:
    if signal.pattern_type not in {"breakout_retest_continuation", "compression_expansion"}:
        return False
    original_bullish = failed.direction == "bullish_to_bearish"
    same_original_direction = signal.direction in (
        {"bullish_continuation", "bullish_breakout"}
        if original_bullish
        else {"bearish_continuation", "bearish_breakout"}
    )
    if not same_original_direction:
        return False
    minutes = abs(int((signal.occurred_at - failed.occurred_at).total_seconds() // 60))
    return minutes <= config.reclaim_max_bars
