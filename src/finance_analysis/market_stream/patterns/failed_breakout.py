"""Failed breakout and failed breakdown reclaim detection."""

from __future__ import annotations

from decimal import Decimal

from finance_analysis.market_stream.patterns.features import PatternContext
from finance_analysis.market_stream.patterns.models import PatternSignal
from finance_analysis.market_stream.patterns.scoring import make_signal


def detect_failed_breakouts(context: PatternContext) -> list[PatternSignal]:
    bars = context.bars
    config = context.config
    atr = context.atr
    signals: list[PatternSignal] = []
    start = max(config.level_lookback, len(bars) - config.maximum_age_bars - config.reclaim_max_bars - 2)
    for breakout_index in range(start, len(bars)):
        reference_bars = bars[breakout_index - config.level_lookback : breakout_index]
        resistance = max(bar.high for bar in reference_bars)
        support = min(bar.low for bar in reference_bars)
        breakout = bars[breakout_index]
        minimum = atr * config.breakout_min_atr

        if breakout.high >= resistance + minimum:
            signal = _bearish_reclaim(context, breakout_index, resistance)
            if signal is not None:
                signals.append(signal)
        if breakout.low <= support - minimum:
            signal = _bullish_reclaim(context, breakout_index, support)
            if signal is not None:
                signals.append(signal)
    return _latest_per_direction(signals)


def _bearish_reclaim(
    context: PatternContext,
    breakout_index: int,
    reference: Decimal,
) -> PatternSignal | None:
    bars, config, atr = context.bars, context.config, context.atr
    reclaim_index = next(
        (
            index
            for index in range(breakout_index + 1, min(len(bars), breakout_index + config.reclaim_max_bars + 1))
            if bars[index].close < reference
        ),
        None,
    )
    if reclaim_index is None:
        return None
    structure_low = min(bar.low for bar in bars[breakout_index : reclaim_index + 1])
    confirmation_index = next(
        (
            index
            for index in range(reclaim_index + 1, len(bars))
            if bars[index].close < structure_low - atr * config.reclaim_confirm_atr
        ),
        None,
    )
    effective_index = confirmation_index if confirmation_index is not None else reclaim_index
    if any(bar.close > reference + atr * config.invalidation_tolerance_atr for bar in bars[reclaim_index + 1 :]):
        return None
    excursion = (bars[breakout_index].high - reference) / atr
    return make_signal(
        context,
        pattern_type="failed_breakout_reclaim",
        pattern_name="假突破前高回收",
        direction="bullish_to_bearish",
        stage="confirmed" if confirmation_index is not None else "warning",
        occurred_index=breakout_index,
        effective_index=effective_index,
        confirmed_index=confirmation_index,
        reference_level=reference,
        invalidation_price=reference + atr * config.invalidation_tolerance_atr,
        base_score=config.failed_breakout_base_score,
        magnitude_atr=excursion,
        reasons=[
            f"向上扫过参考阻力{excursion:.2f} ATR后快速收回",
            "收盘重新回到参考阻力下方",
            *(["随后跌破回收结构低点"] if confirmation_index is not None else []),
        ],
    )


def _bullish_reclaim(
    context: PatternContext,
    breakout_index: int,
    reference: Decimal,
) -> PatternSignal | None:
    bars, config, atr = context.bars, context.config, context.atr
    reclaim_index = next(
        (
            index
            for index in range(breakout_index + 1, min(len(bars), breakout_index + config.reclaim_max_bars + 1))
            if bars[index].close > reference
        ),
        None,
    )
    if reclaim_index is None:
        return None
    structure_high = max(bar.high for bar in bars[breakout_index : reclaim_index + 1])
    confirmation_index = next(
        (
            index
            for index in range(reclaim_index + 1, len(bars))
            if bars[index].close > structure_high + atr * config.reclaim_confirm_atr
        ),
        None,
    )
    effective_index = confirmation_index if confirmation_index is not None else reclaim_index
    if any(bar.close < reference - atr * config.invalidation_tolerance_atr for bar in bars[reclaim_index + 1 :]):
        return None
    excursion = (reference - bars[breakout_index].low) / atr
    return make_signal(
        context,
        pattern_type="failed_breakout_reclaim",
        pattern_name="假跌破前低回收",
        direction="bearish_to_bullish",
        stage="confirmed" if confirmation_index is not None else "warning",
        occurred_index=breakout_index,
        effective_index=effective_index,
        confirmed_index=confirmation_index,
        reference_level=reference,
        invalidation_price=reference - atr * config.invalidation_tolerance_atr,
        base_score=config.failed_breakout_base_score,
        magnitude_atr=excursion,
        reasons=[
            f"向下扫过参考支撑{excursion:.2f} ATR后快速收回",
            "收盘重新回到参考支撑上方",
            *(["随后突破回收结构高点"] if confirmation_index is not None else []),
        ],
    )


def _latest_per_direction(signals: list[PatternSignal]) -> list[PatternSignal]:
    latest: dict[str, PatternSignal] = {}
    for signal in signals:
        current = latest.get(signal.direction)
        if current is None or (_stage_rank(signal.stage), signal.occurred_at) > (
            _stage_rank(current.stage),
            current.occurred_at,
        ):
            latest[signal.direction] = signal
    return list(latest.values())


def _stage_rank(stage: str) -> int:
    return {"forming": 1, "warning": 2, "confirmed": 3}[stage]
