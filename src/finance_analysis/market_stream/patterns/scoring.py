"""Explainable quality scoring and signal construction."""

from __future__ import annotations

from decimal import Decimal

from finance_analysis.market_stream.config import market_trading_date
from finance_analysis.market_stream.patterns.features import PatternContext, volume_ratio
from finance_analysis.market_stream.patterns.models import (
    PatternDirection,
    PatternSignal,
    PatternStage,
    PatternType,
)


def clamp_score(value: int) -> int:
    return max(0, min(100, int(value)))


def age_penalty(context: PatternContext, bars_ago: int) -> int:
    if bars_ago <= context.config.current_age_bars:
        return 0
    if bars_ago <= context.config.recent_age_bars:
        return context.config.recent_age_penalty
    return context.config.historical_age_penalty


def make_signal(
    context: PatternContext,
    *,
    pattern_type: PatternType,
    pattern_name: str,
    direction: PatternDirection,
    stage: PatternStage,
    occurred_index: int,
    effective_index: int,
    confirmed_index: int | None,
    reference_level: Decimal | None,
    invalidation_price: Decimal | None,
    base_score: int,
    magnitude_atr: Decimal,
    reasons: list[str],
) -> PatternSignal | None:
    bars_ago = context.bars_ago(effective_index)
    if bars_ago > context.config.maximum_age_bars:
        return None
    score = base_score + min(
        context.config.strong_structure_bonus,
        max(0, int(magnitude_atr * context.config.structure_score_per_atr)),
    )
    score += (
        context.config.confirmed_score_bonus
        if stage == "confirmed"
        else context.config.warning_score_bonus if stage == "warning" else 0
    )
    ratio = volume_ratio(context.bars[effective_index], context.volume_median)
    if ratio is None:
        score -= context.config.missing_volume_penalty
        reasons.append("成交量缺失，未作为否决条件")
    elif ratio >= context.config.high_volume_ratio:
        score += context.config.volume_score_bonus
        reasons.append("成交量高于近期中位数")
    score -= age_penalty(context, bars_ago)
    if bars_ago > context.config.current_age_bars:
        reasons.append(f"信号已过去{bars_ago}根1分钟K线，质量分已衰减")
    return PatternSignal(
        symbol=context.latest.symbol,
        pattern_type=pattern_type,
        pattern_name=pattern_name,
        direction=direction,
        stage=stage,
        quality_score=clamp_score(score),
        occurred_at=context.bars[occurred_index].bar_time,
        confirmed_at=context.bars[confirmed_index].bar_time if confirmed_index is not None else None,
        trading_date=market_trading_date(context.latest.bar_time, context.market_type),
        trade_session=context.bars[effective_index].trade_session,
        bars_ago=bars_ago,
        session_minutes_ago=context.session_minutes_ago(effective_index),
        reference_level=reference_level,
        invalidation_price=invalidation_price,
        reasons=tuple(reasons),
        confirmed=stage == "confirmed",
    )
