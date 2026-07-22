"""Objective impulse, orderly pullback, and resume detection."""

from __future__ import annotations

from finance_analysis.market_stream.patterns.features import (
    PatternContext,
    average_body,
    average_overlap,
    average_range,
    direction_efficiency,
    directional_close_ratio,
    median_volume,
)
from finance_analysis.market_stream.patterns.models import PatternSignal
from finance_analysis.market_stream.patterns.scoring import make_signal


def detect_impulse_pullbacks(context: PatternContext) -> list[PatternSignal]:
    candidates = [
        *_detect_side(context, bullish=True),
        *_detect_side(context, bullish=False),
    ]
    latest: dict[str, PatternSignal] = {}
    for signal in candidates:
        current = latest.get(signal.direction)
        if current is None or (_stage_rank(signal.stage), signal.occurred_at) > (
            _stage_rank(current.stage),
            current.occurred_at,
        ):
            latest[signal.direction] = signal
    return list(latest.values())


def _detect_side(context: PatternContext, *, bullish: bool) -> list[PatternSignal]:
    bars, config, atr = context.bars, context.config, context.atr
    results: list[PatternSignal] = []
    earliest = max(0, len(bars) - config.maximum_age_bars - config.pullback_max_bars - config.impulse_max_bars)
    for impulse_start in range(earliest, len(bars)):
        for impulse_length in range(config.impulse_min_bars, config.impulse_max_bars + 1):
            impulse_end = impulse_start + impulse_length - 1
            if impulse_end + config.pullback_min_bars >= len(bars):
                continue
            impulse = bars[impulse_start : impulse_end + 1]
            move = impulse[-1].close - impulse[0].close
            if (move <= 0) == bullish or abs(move) < atr * config.impulse_min_atr:
                continue
            if direction_efficiency(impulse) < config.impulse_min_efficiency:
                continue
            if directional_close_ratio(impulse, bullish=bullish) < config.impulse_min_direction_ratio:
                continue
            impulse_body = average_body(impulse)
            if context.body_median > 0 and impulse_body < context.body_median * config.impulse_body_median_ratio:
                continue
            if average_overlap(impulse) > config.impulse_max_overlap:
                continue
            impulse_range = average_range(impulse)
            max_pullback_end = min(len(bars) - 1, impulse_end + config.pullback_max_bars + 1)
            for pullback_end in range(impulse_end + config.pullback_min_bars, max_pullback_end + 1):
                pullback = bars[impulse_end + 1 : pullback_end + 1]
                if bullish:
                    impulse_extreme = max(bar.high for bar in impulse)
                    pullback_extreme = min(bar.low for bar in pullback)
                    retracement = (impulse_extreme - pullback_extreme) / abs(move)
                    core_broken = pullback_extreme <= min(bar.low for bar in impulse)
                else:
                    impulse_extreme = min(bar.low for bar in impulse)
                    pullback_extreme = max(bar.high for bar in pullback)
                    retracement = (pullback_extreme - impulse_extreme) / abs(move)
                    core_broken = pullback_extreme >= max(bar.high for bar in impulse)
                if core_broken or not config.pullback_min_retracement <= retracement <= config.pullback_max_retracement:
                    continue
                if average_body(pullback) > impulse_body * config.pullback_body_ratio:
                    continue
                if average_range(pullback) > impulse_range * config.pullback_range_ratio:
                    continue
                if average_overlap(pullback) < config.pullback_min_overlap:
                    continue
                confirmation_index = None
                pullback_volume_contracts = (
                    median_volume(pullback, len(pullback)) > 0
                    and median_volume(impulse, len(impulse)) > 0
                    and median_volume(pullback, len(pullback)) < median_volume(impulse, len(impulse))
                )
                for index in range(pullback_end + 1, len(bars)):
                    if (
                        bullish
                        and bars[index].close > max(bar.high for bar in pullback) + atr * config.pullback_resume_atr
                    ):
                        confirmation_index = index
                        break
                    if (
                        not bullish
                        and bars[index].close < min(bar.low for bar in pullback) - atr * config.pullback_resume_atr
                    ):
                        confirmation_index = index
                        break
                effective_index = confirmation_index if confirmation_index is not None else pullback_end
                if confirmation_index is None and context.bars_ago(pullback_end) > config.pullback_max_bars:
                    continue
                signal = make_signal(
                    context,
                    pattern_type="impulse_pullback_resume",
                    pattern_name="冲击回撤再启动",
                    direction="bullish_continuation" if bullish else "bearish_continuation",
                    stage="confirmed" if confirmation_index is not None else "forming",
                    occurred_index=impulse_start,
                    effective_index=effective_index,
                    confirmed_index=confirmation_index,
                    reference_level=max(bar.high for bar in pullback) if bullish else min(bar.low for bar in pullback),
                    invalidation_price=min(bar.low for bar in impulse) if bullish else max(bar.high for bar in impulse),
                    base_score=(
                        config.impulse_pullback_base_score
                        + (config.pullback_volume_bonus if pullback_volume_contracts else 0)
                    ),
                    magnitude_atr=abs(move) / atr,
                    reasons=[
                        f"冲击段净幅度{abs(move) / atr:.2f} ATR，方向效率{direction_efficiency(impulse):.2f}",
                        f"有序回撤{retracement * 100:.0f}%，实体和波幅均收缩",
                        *(["回撤阶段成交量中位数低于冲击段"] if pullback_volume_contracts else []),
                        *(["价格突破回撤结构并重新启动"] if confirmation_index is not None else ["回撤结构正在形成"]),
                    ],
                )
                if signal:
                    results.append(signal)
    return results


def _stage_rank(stage: str) -> int:
    return {"forming": 1, "warning": 2, "confirmed": 3}[stage]
