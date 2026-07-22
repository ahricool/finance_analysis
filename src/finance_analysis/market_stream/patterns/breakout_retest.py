"""Breakout, retest, and continuation detection."""

from __future__ import annotations

from decimal import Decimal

from finance_analysis.market_stream.patterns.features import PatternContext, candle_body
from finance_analysis.market_stream.patterns.models import PatternSignal
from finance_analysis.market_stream.patterns.scoring import make_signal


def detect_breakout_retests(context: PatternContext) -> list[PatternSignal]:
    bars, config, atr = context.bars, context.config, context.atr
    candidates: list[PatternSignal] = []
    start = max(config.level_lookback, len(bars) - config.maximum_age_bars - config.retest_max_bars - 2)
    for breakout_index in range(start, len(bars)):
        prior = bars[breakout_index - config.level_lookback : breakout_index]
        resistance = max(bar.high for bar in prior)
        support = min(bar.low for bar in prior)
        bar = bars[breakout_index]
        body_ok = (
            context.body_median <= 0 or candle_body(bar) >= context.body_median * config.breakout_body_median_ratio
        )
        if body_ok and bar.close >= resistance + atr * config.breakout_min_atr:
            signal = _continuation(context, breakout_index, resistance, bullish=True)
            if signal:
                candidates.append(signal)
        if body_ok and bar.close <= support - atr * config.breakout_min_atr:
            signal = _continuation(context, breakout_index, support, bullish=False)
            if signal:
                candidates.append(signal)
    latest: dict[str, PatternSignal] = {}
    for signal in candidates:
        current = latest.get(signal.direction)
        if current is None or (_stage_rank(signal.stage), signal.occurred_at) > (
            _stage_rank(current.stage),
            current.occurred_at,
        ):
            latest[signal.direction] = signal
    return list(latest.values())


def _continuation(
    context: PatternContext,
    breakout_index: int,
    reference: Decimal,
    *,
    bullish: bool,
) -> PatternSignal | None:
    bars, config, atr = context.bars, context.config, context.atr
    end = min(len(bars), breakout_index + config.retest_max_bars + 1)
    follow = range(breakout_index + 1, end)
    prior = bars[breakout_index - config.level_lookback : breakout_index]
    if bullish:
        invalid = _has_consecutive(
            [bars[index].close < reference - atr * config.retest_penetration_atr for index in follow],
            config.retest_invalidation_closes,
        )
        touch_index = next(
            (index for index in follow if bars[index].low <= reference + atr * config.retest_penetration_atr),
            None,
        )
        invalid = invalid or any(
            bars[index].low < min(bar.low for bar in prior) - atr * config.retest_penetration_atr for index in follow
        )
    else:
        invalid = _has_consecutive(
            [bars[index].close > reference + atr * config.retest_penetration_atr for index in follow],
            config.retest_invalidation_closes,
        )
        touch_index = next(
            (index for index in follow if bars[index].high >= reference - atr * config.retest_penetration_atr),
            None,
        )
        invalid = invalid or any(
            bars[index].high > max(bar.high for bar in prior) + atr * config.retest_penetration_atr for index in follow
        )
    if invalid:
        return None

    confirmation_index: int | None = None
    if touch_index is not None:
        for index in range(touch_index + 1, end):
            retest = bars[touch_index:index]
            if bullish and bars[index].close > max(bar.high for bar in retest) + atr * config.retest_resume_atr:
                confirmation_index = index
                break
            if not bullish and bars[index].close < min(bar.low for bar in retest) - atr * config.retest_resume_atr:
                confirmation_index = index
                break
    if confirmation_index is None and context.bars_ago(breakout_index) > config.retest_max_bars:
        return None
    effective_index = confirmation_index if confirmation_index is not None else breakout_index
    excursion = abs(bars[breakout_index].close - reference) / atr
    return make_signal(
        context,
        pattern_type="breakout_retest_continuation",
        pattern_name="向上突破回踩" if bullish else "向下突破反抽",
        direction="bullish_continuation" if bullish else "bearish_continuation",
        stage="confirmed" if confirmation_index is not None else "warning",
        occurred_index=breakout_index,
        effective_index=effective_index,
        confirmed_index=confirmation_index,
        reference_level=reference,
        invalidation_price=(
            reference - atr * config.retest_penetration_atr
            if bullish
            else reference + atr * config.retest_penetration_atr
        ),
        base_score=config.breakout_retest_base_score,
        magnitude_atr=excursion,
        reasons=[
            f"实体收盘有效{'突破阻力' if bullish else '跌破支撑'}{excursion:.2f} ATR",
            *(["回踩参考位后重新向原方向扩张"] if confirmation_index is not None else ["等待回踩与延续确认"]),
        ],
    )


def _has_consecutive(values: list[bool], count: int) -> bool:
    streak = 0
    for value in values:
        streak = streak + 1 if value else 0
        if streak >= count:
            return True
    return False


def _stage_rank(stage: str) -> int:
    return {"forming": 1, "warning": 2, "confirmed": 3}[stage]
