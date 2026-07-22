"""Pure shared features used by all realtime multi-bar detectors."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import median

from finance_analysis.integrations.market_data.realtime_state.models import CandleState
from finance_analysis.market_stream.config import (
    is_regular_session_minute,
    is_regular_trade_session,
    market_spec,
    market_trading_date,
)
from finance_analysis.market_stream.patterns.config import PatternConfig
from finance_analysis.stocks.markets import MarketType

ZERO = Decimal("0")
ONE = Decimal("1")


def median_decimal(values: Sequence[Decimal]) -> Decimal:
    return Decimal(median(values)) if values else ZERO


def true_range(bar: CandleState, previous_close: Decimal | None = None) -> Decimal:
    width = max(ZERO, bar.high - bar.low)
    if previous_close is None:
        return width
    return max(width, abs(bar.high - previous_close), abs(bar.low - previous_close))


def true_ranges(bars: Sequence[CandleState]) -> list[Decimal]:
    result: list[Decimal] = []
    previous_close: Decimal | None = None
    for bar in bars:
        result.append(true_range(bar, previous_close))
        previous_close = bar.close
    return result


def robust_atr(bars: Sequence[CandleState], window: int) -> Decimal:
    if not bars:
        return ZERO
    return median_decimal(true_ranges(bars)[-max(1, window) :])


def candle_body(bar: CandleState) -> Decimal:
    return abs(bar.close - bar.open)


def upper_wick(bar: CandleState) -> Decimal:
    return max(ZERO, bar.high - max(bar.open, bar.close))


def lower_wick(bar: CandleState) -> Decimal:
    return max(ZERO, min(bar.open, bar.close) - bar.low)


def body_ratio(bar: CandleState) -> Decimal:
    width = bar.high - bar.low
    return candle_body(bar) / width if width > ZERO else ZERO


def median_body(bars: Sequence[CandleState], window: int) -> Decimal:
    return median_decimal([candle_body(bar) for bar in bars[-max(1, window) :]])


def median_volume(bars: Sequence[CandleState], window: int) -> Decimal:
    values = [Decimal(bar.volume) for bar in bars[-max(1, window) :] if bar.volume > 0]
    return median_decimal(values)


def volume_ratio(bar: CandleState, baseline: Decimal) -> Decimal | None:
    if bar.volume <= 0 or baseline <= ZERO:
        return None
    return Decimal(bar.volume) / baseline


def adjacent_overlap(left: CandleState, right: CandleState) -> Decimal:
    overlap = max(ZERO, min(left.high, right.high) - max(left.low, right.low))
    denominator = min(left.high - left.low, right.high - right.low)
    return min(ONE, overlap / denominator) if denominator > ZERO else ZERO


def average_overlap(bars: Sequence[CandleState]) -> Decimal:
    if len(bars) < 2:
        return ZERO
    values = [adjacent_overlap(left, right) for left, right in zip(bars, bars[1:])]
    return sum(values, ZERO) / Decimal(len(values))


def range_width(bars: Sequence[CandleState]) -> Decimal:
    if not bars:
        return ZERO
    return max(bar.high for bar in bars) - min(bar.low for bar in bars)


def average_range(bars: Sequence[CandleState]) -> Decimal:
    return sum((bar.high - bar.low for bar in bars), ZERO) / Decimal(len(bars)) if bars else ZERO


def average_body(bars: Sequence[CandleState]) -> Decimal:
    return sum((candle_body(bar) for bar in bars), ZERO) / Decimal(len(bars)) if bars else ZERO


def direction_efficiency(bars: Sequence[CandleState]) -> Decimal:
    if len(bars) < 2:
        return ZERO
    changes = [right.close - left.close for left, right in zip(bars, bars[1:])]
    path = sum((abs(change) for change in changes), ZERO)
    return abs(bars[-1].close - bars[0].close) / path if path > ZERO else ZERO


def directional_close_ratio(bars: Sequence[CandleState], *, bullish: bool) -> Decimal:
    if len(bars) < 2:
        return ZERO
    changes = [right.close - left.close for left, right in zip(bars, bars[1:])]
    aligned = (
        sum(1 for change in changes if change > ZERO) if bullish else sum(1 for change in changes if change < ZERO)
    )
    return Decimal(aligned) / Decimal(len(changes))


def swing_high_indices(bars: Sequence[CandleState], span: int) -> list[int]:
    if span < 1:
        raise ValueError("swing span must be positive")
    return [
        index
        for index in range(span, len(bars) - span)
        if bars[index].high >= max(bar.high for bar in bars[index - span : index])
        and bars[index].high > max(bar.high for bar in bars[index + 1 : index + span + 1])
    ]


def swing_low_indices(bars: Sequence[CandleState], span: int) -> list[int]:
    if span < 1:
        raise ValueError("swing span must be positive")
    return [
        index
        for index in range(span, len(bars) - span)
        if bars[index].low <= min(bar.low for bar in bars[index - span : index])
        and bars[index].low < min(bar.low for bar in bars[index + 1 : index + span + 1])
    ]


def rolling_high(bars: Sequence[CandleState]) -> Decimal | None:
    return max((bar.high for bar in bars), default=None)


def rolling_low(bars: Sequence[CandleState]) -> Decimal | None:
    return min((bar.low for bar in bars), default=None)


def normalized_distance(price: Decimal, reference: Decimal, atr: Decimal, epsilon: Decimal) -> Decimal:
    denominator = max(atr, epsilon)
    return (price - reference) / denominator


def sanitize_bars(bars: Sequence[CandleState], market_type: MarketType) -> list[CandleState]:
    """Return deduplicated confirmed regular-session bars for the latest trading date in the input."""
    candidates: dict[tuple[datetime, str], CandleState] = {}
    for bar in bars:
        if (
            not bar.confirmed
            or not bar.is_valid()
            or bar.bar_time.tzinfo is None
            or bar.bar_time.utcoffset() is None
            or not is_regular_session_minute(bar.bar_time, market_type)
            or not is_regular_trade_session(bar.trade_session)
        ):
            continue
        previous = candidates.get(bar.identity)
        if previous is None or bar.received_at >= previous.received_at:
            candidates[bar.identity] = bar
    ordered = sorted(candidates.values(), key=lambda bar: (bar.bar_time, bar.trade_session or ""))
    if not ordered:
        return []
    target_date = market_trading_date(ordered[-1].bar_time, market_type)
    return [bar for bar in ordered if market_trading_date(bar.bar_time, market_type) == target_date]


def session_minute_index(value: datetime, market_type: MarketType) -> int:
    spec = market_spec(market_type)
    local = value.astimezone(spec.timezone)
    current = local.time().replace(tzinfo=None)
    elapsed = 0
    for start, end in spec.regular_sessions:
        session_minutes = int(
            (
                datetime.combine(local.date(), end, tzinfo=spec.timezone)
                - datetime.combine(local.date(), start, tzinfo=spec.timezone)
            ).total_seconds()
            // 60
        )
        if current < start:
            return elapsed
        if current < end:
            return elapsed + int(
                (
                    datetime.combine(local.date(), current, tzinfo=spec.timezone)
                    - datetime.combine(local.date(), start, tzinfo=spec.timezone)
                ).total_seconds()
                // 60
            )
        elapsed += session_minutes
    return elapsed


def session_minutes_between(earlier: CandleState, later: CandleState, market_type: MarketType) -> int:
    if market_trading_date(earlier.bar_time, market_type) != market_trading_date(later.bar_time, market_type):
        return 0
    return max(
        0, session_minute_index(later.bar_time, market_type) - session_minute_index(earlier.bar_time, market_type)
    )


def session_vwap(
    bars: Sequence[CandleState],
    *,
    atr: Decimal,
    config: PatternConfig,
) -> list[Decimal | None]:
    """Calculate cumulative session VWAP, validating turnover and falling back to typical price."""
    cumulative_value = ZERO
    cumulative_volume = Decimal("0")
    result: list[Decimal | None] = []
    tolerance = max(atr * config.vwap_price_tolerance_atr, config.atr_epsilon)
    for bar in bars:
        if bar.volume <= 0:
            result.append(cumulative_value / cumulative_volume if cumulative_volume > ZERO else None)
            continue
        volume = Decimal(bar.volume)
        typical = (bar.high + bar.low + bar.close) / Decimal("3")
        value = typical * volume
        if bar.turnover is not None and bar.turnover > ZERO:
            implied_price = bar.turnover / volume
            if bar.low - tolerance <= implied_price <= bar.high + tolerance:
                value = bar.turnover
        cumulative_value += value
        cumulative_volume += volume
        result.append(cumulative_value / cumulative_volume)
    return result


@dataclass(frozen=True, slots=True)
class PatternContext:
    bars: tuple[CandleState, ...]
    market_type: MarketType
    config: PatternConfig
    atr: Decimal
    body_median: Decimal
    volume_median: Decimal
    vwaps: tuple[Decimal | None, ...]

    @property
    def latest(self) -> CandleState:
        return self.bars[-1]

    def bars_ago(self, index: int) -> int:
        return len(self.bars) - 1 - index

    def session_minutes_ago(self, index: int) -> int:
        return session_minutes_between(self.bars[index], self.latest, self.market_type)


def prepare_context(
    bars: Sequence[CandleState],
    *,
    market_type: MarketType,
    config: PatternConfig,
) -> PatternContext | None:
    ordered = sanitize_bars(bars, market_type)
    if len(ordered) < config.minimum_history_bars:
        return None
    atr = robust_atr(ordered, config.baseline_window)
    if atr <= config.atr_epsilon:
        return None
    return PatternContext(
        bars=tuple(ordered),
        market_type=market_type,
        config=config,
        atr=atr,
        body_median=median_body(ordered, config.baseline_window),
        volume_median=median_volume(ordered, config.baseline_window),
        vwaps=tuple(session_vwap(ordered, atr=atr, config=config)),
    )
