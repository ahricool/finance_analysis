"""Session VWAP reclaim/breakdown with retest confirmation."""

from __future__ import annotations

from decimal import Decimal

from finance_analysis.market_stream.patterns.features import PatternContext
from finance_analysis.market_stream.patterns.models import PatternSignal
from finance_analysis.market_stream.patterns.scoring import make_signal


def detect_vwap_patterns(context: PatternContext) -> list[PatternSignal]:
    bars, config, atr = context.bars, context.config, context.atr
    candidates: list[PatternSignal] = []
    start = max(config.vwap_prior_bars, len(bars) - config.maximum_age_bars - config.vwap_retest_max_bars - 2)
    for cross_index in range(start, len(bars)):
        vwap = context.vwaps[cross_index]
        if vwap is None:
            continue
        prior_indices = range(cross_index - config.vwap_prior_bars, cross_index)
        comparable = [index for index in prior_indices if context.vwaps[index] is not None]
        if len(comparable) < config.vwap_prior_bars:
            continue
        below_ratio = Decimal(sum(bars[index].close < context.vwaps[index] for index in comparable)) / Decimal(
            len(comparable)
        )
        above_ratio = Decimal(sum(bars[index].close > context.vwaps[index] for index in comparable)) / Decimal(
            len(comparable)
        )
        if (
            below_ratio >= config.vwap_prior_side_ratio
            and bars[cross_index].close >= vwap + atr * config.vwap_cross_atr
        ):
            signal = _retest(context, cross_index, bullish=True, prior_ratio=below_ratio)
            if signal:
                candidates.append(signal)
        if (
            above_ratio >= config.vwap_prior_side_ratio
            and bars[cross_index].close <= vwap - atr * config.vwap_cross_atr
        ):
            signal = _retest(context, cross_index, bullish=False, prior_ratio=above_ratio)
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


def _retest(
    context: PatternContext,
    cross_index: int,
    *,
    bullish: bool,
    prior_ratio: Decimal,
) -> PatternSignal | None:
    bars, config, atr = context.bars, context.config, context.atr
    end = min(len(bars), cross_index + config.vwap_retest_max_bars + 1)
    follow = range(cross_index + 1, end)
    invalid_values: list[bool] = []
    touch_index = None
    for index in follow:
        vwap = context.vwaps[index]
        if vwap is None:
            continue
        if bullish:
            invalid_values.append(bars[index].close < vwap - atr * config.vwap_retest_tolerance_atr)
            if touch_index is None and bars[index].low <= vwap + atr * config.vwap_retest_tolerance_atr:
                touch_index = index
        else:
            invalid_values.append(bars[index].close > vwap + atr * config.vwap_retest_tolerance_atr)
            if touch_index is None and bars[index].high >= vwap - atr * config.vwap_retest_tolerance_atr:
                touch_index = index
    if _has_consecutive(invalid_values, config.vwap_invalidation_closes):
        return None
    confirmation_index = None
    if touch_index is not None:
        for index in range(touch_index + 1, end):
            retest = bars[touch_index:index]
            if bullish and bars[index].close > max(bar.high for bar in retest) + atr * config.vwap_resume_atr:
                confirmation_index = index
                break
            if not bullish and bars[index].close < min(bar.low for bar in retest) - atr * config.vwap_resume_atr:
                confirmation_index = index
                break
    if confirmation_index is None and context.bars_ago(cross_index) > config.vwap_retest_max_bars:
        return None
    effective_index = confirmation_index if confirmation_index is not None else cross_index
    reference = context.vwaps[effective_index] or context.vwaps[cross_index]
    assert reference is not None
    distance = abs(bars[cross_index].close - (context.vwaps[cross_index] or reference)) / atr
    return make_signal(
        context,
        pattern_type="vwap_reclaim_breakdown",
        pattern_name="VWAP收复回踩" if bullish else "VWAP跌破反抽",
        direction="bearish_to_bullish" if bullish else "bullish_to_bearish",
        stage="confirmed" if confirmation_index is not None else "warning",
        occurred_index=cross_index,
        effective_index=effective_index,
        confirmed_index=confirmation_index,
        reference_level=reference,
        invalidation_price=(
            reference - atr * config.vwap_retest_tolerance_atr
            if bullish
            else reference + atr * config.vwap_retest_tolerance_atr
        ),
        base_score=config.vwap_base_score,
        magnitude_atr=distance,
        reasons=[
            f"此前{prior_ratio * 100:.0f}%的收盘位于VWAP{'下方' if bullish else '上方'}",
            f"收盘有效{'收复' if bullish else '跌破'}当日累计VWAP",
            *(["回踩VWAP后突破局部结构并确认"] if confirmation_index is not None else ["等待VWAP回踩确认"]),
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
