"""Public orchestration API and deterministic primary-signal selection."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from finance_analysis.integrations.market_data.realtime_state.models import CandleState, QuoteState
from finance_analysis.market_stream.config import market_trading_date
from finance_analysis.market_stream.patterns.breakout_retest import detect_breakout_retests
from finance_analysis.market_stream.patterns.compression import detect_compressions
from finance_analysis.market_stream.patterns.config import PatternConfig
from finance_analysis.market_stream.patterns.double_top_bottom import detect_double_patterns
from finance_analysis.market_stream.patterns.failed_breakout import detect_failed_breakouts
from finance_analysis.market_stream.patterns.features import prepare_context, prepare_preview_bars, sanitize_bars
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
PREVIEW_REASON = "实时预览：当前一分钟K线尚未收盘，信号可能变化"


def detect_pattern_signals(
    bars: Sequence[CandleState],
    *,
    market_type: MarketType,
    config: PatternConfig | None = None,
    preview: bool = False,
) -> list[PatternSignal]:
    """Detect candidates from formal bars, or an explicitly prepared preview sequence."""
    selected_config = config or PatternConfig()
    context = prepare_context(bars, market_type=market_type, config=selected_config, preview=preview)
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
    include_preview: bool = False,
    quote: QuoteState | None = None,
) -> PatternState:
    """Build formal state and, when requested, a non-confirming unfinished-bar preview."""
    selected_config = config or PatternConfig()
    ordered = sanitize_bars(bars, market_type)
    symbol = ordered[-1].symbol if ordered else next((bar.symbol for bar in bars), "")
    if not ordered:
        formal = PatternState(symbol=symbol)
    else:
        trading_date = market_trading_date(ordered[-1].bar_time, market_type)
        if prepare_context(ordered, market_type=market_type, config=selected_config) is None:
            formal = PatternState(
                symbol=symbol,
                status="insufficient",
                trading_date=trading_date,
                bar_time=ordered[-1].bar_time,
            )
        else:
            signals = detect_pattern_signals(ordered, market_type=market_type, config=selected_config)
            primary = select_primary_pattern(
                signals,
                latest_bar_time=ordered[-1].bar_time,
                config=selected_config,
            )
            formal = PatternState(
                symbol=symbol,
                status="active" if primary else "none",
                signal=primary,
                trading_date=trading_date,
                bar_time=ordered[-1].bar_time,
            )
    if not include_preview:
        return formal

    preview_bars = prepare_preview_bars(bars, market_type, quote=quote)
    unfinished = preview_bars[-1] if preview_bars and not preview_bars[-1].confirmed else None
    if unfinished is None:
        return replace(formal, preview_status="none" if ordered else "insufficient")
    preview_context = prepare_context(preview_bars, market_type=market_type, config=selected_config, preview=True)
    if preview_context is None:
        return replace(
            formal,
            preview_status="insufficient",
            preview_bar_time=unfinished.bar_time,
            preview_price=unfinished.close,
            preview_updated_at=unfinished.received_at,
        )
    preview_signals = detect_pattern_signals(
        preview_bars,
        market_type=market_type,
        config=selected_config,
        preview=True,
    )
    preview_signal = select_primary_pattern(
        preview_signals,
        latest_bar_time=unfinished.bar_time,
        config=selected_config,
    )
    if preview_signal is not None:
        reasons = preview_signal.reasons
        if PREVIEW_REASON not in reasons:
            reasons = (*reasons, PREVIEW_REASON)
        preview_signal = replace(
            preview_signal,
            stage="warning" if preview_signal.stage == "confirmed" else preview_signal.stage,
            confirmed=False,
            confirmed_at=None,
            reasons=reasons,
        )
    return replace(
        formal,
        preview_status="active" if preview_signal else "none",
        preview_signal=preview_signal,
        preview_bar_time=unfinished.bar_time,
        preview_price=unfinished.close,
        preview_updated_at=unfinished.received_at,
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
