"""Volatility compression and held expansion breakout detection."""

from __future__ import annotations

from finance_analysis.market_stream.patterns.features import (
    PatternContext,
    average_body,
    average_overlap,
    average_range,
    candle_body,
    median_volume,
    range_width,
)
from finance_analysis.market_stream.patterns.models import PatternSignal
from finance_analysis.market_stream.patterns.scoring import make_signal


def detect_compressions(context: PatternContext) -> list[PatternSignal]:
    bars, config, atr = context.bars, context.config, context.atr
    candidates: list[PatternSignal] = []
    earliest_end = config.compression_reference_bars + config.compression_min_bars - 1
    start_end = max(earliest_end, len(bars) - config.maximum_age_bars - config.compression_failure_bars - 2)
    for compression_end in range(start_end, len(bars)):
        for window in range(config.compression_min_bars, config.compression_max_bars + 1):
            compression_start = compression_end - window + 1
            reference_start = compression_start - config.compression_reference_bars
            if reference_start < 0:
                continue
            compact = bars[compression_start : compression_end + 1]
            reference = bars[reference_start:compression_start]
            if average_range(compact) > average_range(reference) * config.compression_range_ratio:
                continue
            if range_width(compact) > atr * config.compression_width_atr:
                continue
            if average_overlap(compact) < config.compression_min_overlap:
                continue
            if context.body_median > 0 and average_body(compact) > context.body_median * config.compression_body_ratio:
                continue
            upper = max(bar.high for bar in compact)
            lower = min(bar.low for bar in compact)
            volume_contracts = (
                median_volume(compact, len(compact)) > 0
                and median_volume(reference, len(reference)) > 0
                and median_volume(compact, len(compact)) < median_volume(reference, len(reference))
            )
            breakout_index = compression_end + 1
            if breakout_index >= len(bars):
                signal = make_signal(
                    context,
                    pattern_type="compression_expansion",
                    pattern_name="波动压缩",
                    direction="neutral_wait",
                    stage="forming",
                    occurred_index=compression_start,
                    effective_index=compression_end,
                    confirmed_index=None,
                    reference_level=(upper + lower) / 2,
                    invalidation_price=None,
                    base_score=config.compression_base_score
                    + (config.compression_volume_bonus if volume_contracts else 0),
                    magnitude_atr=range_width(reference) / atr,
                    reasons=[
                        "短期平均波幅低于此前参考窗口",
                        f"相邻K线平均重叠率{average_overlap(compact) * 100:.0f}%",
                        *(["压缩阶段成交量中位数同步下降"] if volume_contracts else []),
                        "等待价格有效离开压缩区间",
                    ],
                )
                if signal:
                    candidates.append(signal)
                continue
            breakout = bars[breakout_index]
            bullish = breakout.close >= upper + atr * config.breakout_min_atr
            bearish = breakout.close <= lower - atr * config.breakout_min_atr
            if not bullish and not bearish:
                continue
            if (
                context.body_median > 0
                and candle_body(breakout) < context.body_median * config.compression_breakout_body_ratio
            ):
                continue
            hold_end = breakout_index + config.compression_hold_bars
            if hold_end >= len(bars):
                continue
            failure_end = min(len(bars), breakout_index + config.compression_failure_bars + 1)
            failed = any(lower <= bars[index].close <= upper for index in range(breakout_index + 1, failure_end))
            if failed:
                continue
            confirmation_index = hold_end
            distance = (breakout.close - upper) / atr if bullish else (lower - breakout.close) / atr
            signal = make_signal(
                context,
                pattern_type="compression_expansion",
                pattern_name="波动压缩扩张",
                direction="bullish_breakout" if bullish else "bearish_breakout",
                stage="confirmed",
                occurred_index=breakout_index,
                effective_index=confirmation_index,
                confirmed_index=confirmation_index,
                reference_level=upper if bullish else lower,
                invalidation_price=lower if bullish else upper,
                base_score=config.compression_base_score + (config.compression_volume_bonus if volume_contracts else 0),
                magnitude_atr=distance,
                reasons=[
                    "此前区间波幅、实体同步收缩且重叠率提高",
                    *(["压缩阶段成交量中位数同步下降"] if volume_contracts else []),
                    f"突破实体明显扩张并离开区间{distance:.2f} ATR",
                    f"后续{config.compression_hold_bars}根已闭合K线未立即收回区间",
                ],
            )
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


def _stage_rank(stage: str) -> int:
    return {"forming": 1, "warning": 2, "confirmed": 3}[stage]
