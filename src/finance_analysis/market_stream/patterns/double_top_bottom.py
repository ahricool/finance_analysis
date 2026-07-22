"""Micro double bottom/top detection with mandatory neckline confirmation."""

from __future__ import annotations

from decimal import Decimal

from finance_analysis.market_stream.patterns.features import PatternContext, swing_high_indices, swing_low_indices
from finance_analysis.market_stream.patterns.models import PatternSignal
from finance_analysis.market_stream.patterns.scoring import make_signal


def detect_double_patterns(context: PatternContext) -> list[PatternSignal]:
    signals = [
        *_detect_side(context, bullish=True),
        *_detect_side(context, bullish=False),
    ]
    latest: dict[str, PatternSignal] = {}
    for signal in signals:
        current = latest.get(signal.direction)
        if current is None or (_stage_rank(signal.stage), signal.occurred_at) > (
            _stage_rank(current.stage),
            current.occurred_at,
        ):
            latest[signal.direction] = signal
    return list(latest.values())


def _detect_side(context: PatternContext, *, bullish: bool) -> list[PatternSignal]:
    bars, config, atr = context.bars, context.config, context.atr
    swings = swing_low_indices(bars, config.swing_span) if bullish else swing_high_indices(bars, config.swing_span)
    results: list[PatternSignal] = []
    for first_position, first_index in enumerate(swings):
        for second_index in swings[first_position + 1 :]:
            separation = second_index - first_index
            if separation < config.double_min_separation:
                continue
            if separation > config.double_max_separation:
                break
            first_level = bars[first_index].low if bullish else bars[first_index].high
            second_level = bars[second_index].low if bullish else bars[second_index].high
            if abs(second_level - first_level) > atr * config.double_level_tolerance_atr:
                continue
            if bullish and second_level < first_level - atr * config.double_level_tolerance_atr:
                continue
            if not bullish and second_level > first_level + atr * config.double_level_tolerance_atr:
                continue
            middle = bars[first_index + 1 : second_index]
            if not middle:
                continue
            neckline = max(bar.high for bar in middle) if bullish else min(bar.low for bar in middle)
            base_level = min(first_level, second_level) if bullish else max(first_level, second_level)
            bounce = neckline - base_level if bullish else base_level - neckline
            if bounce < atr * config.double_neckline_min_atr:
                continue

            confirmation_end = min(len(bars), second_index + config.double_confirmation_max_bars + 1)
            after_second = range(second_index + 1, confirmation_end)
            invalidated = any(
                (
                    bars[index].close < base_level - atr * config.double_invalidation_atr
                    if bullish
                    else bars[index].close > base_level + atr * config.double_invalidation_atr
                )
                for index in range(second_index + 1, len(bars))
            )
            if invalidated:
                continue
            confirmation_index = next(
                (
                    index
                    for index in after_second
                    if (
                        bars[index].close > neckline + atr * config.double_breakout_atr
                        if bullish
                        else bars[index].close < neckline - atr * config.double_breakout_atr
                    )
                ),
                None,
            )
            if confirmation_index is None and context.bars_ago(second_index) > config.double_confirmation_max_bars:
                continue
            effective_index = confirmation_index if confirmation_index is not None else second_index
            signal = make_signal(
                context,
                pattern_type="micro_double_bottom_top",
                pattern_name="微型双底" if bullish else "微型双顶",
                direction="bearish_to_bullish" if bullish else "bullish_to_bearish",
                stage="confirmed" if confirmation_index is not None else "warning",
                occurred_index=first_index,
                effective_index=effective_index,
                confirmed_index=confirmation_index,
                reference_level=neckline,
                invalidation_price=(
                    base_level - atr * config.double_invalidation_atr
                    if bullish
                    else base_level + atr * config.double_invalidation_atr
                ),
                base_score=config.double_pattern_base_score,
                magnitude_atr=bounce / atr,
                reasons=[
                    f"两次测试间隔{separation}根K线，价差处于ATR容差内",
                    f"中间颈线反弹幅度为{bounce / atr:.2f} ATR",
                    *(["收盘有效突破颈线"] if confirmation_index is not None and bullish else []),
                    *(["收盘有效跌破颈线"] if confirmation_index is not None and not bullish else []),
                    *(["第二次测试成立，等待颈线突破"] if confirmation_index is None else []),
                ],
            )
            if signal:
                results.append(signal)
    return results


def _stage_rank(stage: str) -> int:
    return {"forming": 1, "warning": 2, "confirmed": 3}[stage]
