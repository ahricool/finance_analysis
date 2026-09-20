# -*- coding: utf-8 -*-
"""5m indicators for V1 soft exits. Unknown values stay unknown; missing RVOL does not drop OR."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import median
from typing import Sequence

from finance_analysis.trade_engine.bars import NormalizedBar, adjacent, is_complete_session_day, opening_observation_ends, session_prefix_ends  # pragma: allowlist secret
from finance_analysis.trade_engine.config import RiskPolicy  # pragma: allowlist secret

EMA_SEED = 20


@dataclass(frozen=True, slots=True)
class BarIndicators:
    bar: NormalizedBar
    ema20: Decimal | None
    ema_ready: bool
    vwap: Decimal | None
    vwap_mode: str
    previous_30m_low: Decimal | None
    rvol: Decimal | None
    opening_observation: bool
    gap_before: bool


def ema20_series(closes: Sequence[Decimal], *, warmup: int, period: int = EMA_SEED) -> list[Decimal | None]:
    values: list[Decimal | None] = [None] * len(closes)
    if len(closes) < period:
        return values
    seed = sum(closes[:period], start=Decimal("0")) / Decimal(period)
    values[period - 1] = seed
    multiplier = Decimal(2) / Decimal(period + 1)
    previous = seed
    for index in range(period, len(closes)):
        previous = multiplier * closes[index] + (Decimal(1) - multiplier) * previous
        values[index] = previous
    if len(closes) < warmup:
        return [None for _ in values]
    ready = [None if index < warmup - 1 else value for index, value in enumerate(values)]
    return ready


def _session_prefix(bars: Sequence[NormalizedBar], current: NormalizedBar) -> list[NormalizedBar]:
    return [bar for bar in bars if bar.session_id == current.session_id and bar.bar_end < current.bar_end]


def previous_30m_low(bars: Sequence[NormalizedBar], current: NormalizedBar, *, count: int = 6) -> Decimal | None:
    prior = _session_prefix(bars, current)
    if len(prior) < count:
        return None
    window = prior[-count:]
    if any(not adjacent(window[index], window[index + 1]) for index in range(len(window) - 1)):
        return None
    if not adjacent(window[-1], current) and window[-1].bar_end != current.bar_start:
        if window[-1].bar_end != current.bar_start:
            return None
    return min(bar.low for bar in window)


def vwap_until(
    day_bars: Sequence[NormalizedBar],
    current: NormalizedBar,
    *,
    mode: str,
) -> tuple[Decimal | None, str]:
    window = [bar for bar in day_bars if bar.trade_date == current.trade_date and bar.bar_end <= current.bar_end]
    if not window:
        return None, "UNAVAILABLE"
    expected_ends = session_prefix_ends(current.market, current.bar_end)
    present = {bar.bar_end: bar for bar in window}
    if not expected_ends or any(end not in present for end in expected_ends):
        return None, "UNAVAILABLE"
    expected = [present[end] for end in expected_ends]
    if any(bar.volume_quality == "unreliable" for bar in expected):
        return None, "UNAVAILABLE"
    volumes = [bar.volume for bar in expected]
    if sum(volumes) <= 0:
        return None, "UNAVAILABLE"
    exact = all(bar.amount_quality == "exact" and bar.amount is not None for bar in expected)
    if exact:
        total_amount = sum((bar.amount for bar in expected), start=Decimal("0"))
        total_volume = Decimal(sum(volumes))
        if total_volume <= 0:
            return None, "UNAVAILABLE"
        return total_amount / total_volume, "EXACT"
    if mode == "exact_only":
        return None, "UNAVAILABLE"
    typical_sum = Decimal("0")
    total_volume = Decimal("0")
    for bar in expected:
        typical = (bar.high + bar.low + bar.close) / Decimal(3)
        typical_sum += typical * Decimal(bar.volume)
        total_volume += Decimal(bar.volume)
    if total_volume <= 0:
        return None, "UNAVAILABLE"
    return typical_sum / total_volume, "PROXY"


def rvol(
    history: Sequence[NormalizedBar],
    current: NormalizedBar,
    *,
    days: int,
    market: str,
) -> Decimal | None:
    if current.volume_quality != "ok" or current.volume <= 0:
        return None
    by_date: dict = {}
    for bar in history:
        if bar.slot_key != current.slot_key or bar.trade_date >= current.trade_date:
            continue
        by_date.setdefault(bar.trade_date, []).append(bar)
    complete_days = []
    for trade_date, bars in sorted(by_date.items()):
        if not is_complete_session_day(market, trade_date, [item for item in history if item.trade_date == trade_date]):
            continue
        match = next((item for item in bars if item.slot_key == current.slot_key), None)
        if match is None or match.volume_quality != "ok" or match.volume <= 0:
            continue
        complete_days.append(match.volume)
    if len(complete_days) < days:
        return None
    baseline = median(complete_days[-days:])
    if baseline <= 0:
        return None
    return Decimal(current.volume) / Decimal(baseline)


def annotate(
    bars: Sequence[NormalizedBar],
    *,
    policy: RiskPolicy,
    market: str,
    now: datetime,
) -> list[BarIndicators]:
    closed = [bar for bar in bars if bar.closed]
    closes = [bar.close for bar in closed]
    ema_values = ema20_series(closes, warmup=policy.ema_warmup, period=policy.ema_period)
    annotated: list[BarIndicators] = []
    previous = None
    for index, bar in enumerate(closed):
        day_bars = [item for item in closed if item.trade_date == bar.trade_date]
        vwap, vwap_mode = vwap_until(day_bars, bar, mode=policy.vwap_mode)
        gap_before = previous is not None and not adjacent(previous, bar)
        annotated.append(
            BarIndicators(
                bar=bar,
                ema20=ema_values[index],
                ema_ready=ema_values[index] is not None,
                vwap=vwap,
                vwap_mode=vwap_mode,
                previous_30m_low=previous_30m_low(closed, bar, count=policy.structure_bars),
                rvol=rvol(closed, bar, days=policy.rvol_days, market=market),
                opening_observation=bar.bar_end in opening_observation_ends(market, bar.trade_date),
                gap_before=gap_before,
            )
        )
        previous = bar
    return annotated


def ordinary_weak(row: BarIndicators, policy: RiskPolicy) -> bool | None:
    if row.ema20 is None or row.vwap is None:
        return None
    if row.bar.close >= row.ema20 or row.bar.close >= row.vwap:
        return False
    structure = None if row.previous_30m_low is None else row.bar.close < row.previous_30m_low
    volume = None if row.rvol is None else row.rvol >= policy.rvol_weak
    if structure is True or volume is True:
        return True
    if structure is False and volume is False:
        return False
    if structure is False and volume is None:
        return False
    if structure is None and volume is False:
        return False
    return None


def severe_break(row: BarIndicators, policy: RiskPolicy) -> bool | None:
    bar = row.bar
    required = (
        row.ema20,
        row.vwap,
        row.previous_30m_low,
        row.rvol,
    )
    if any(item is None for item in required):
        return None
    if bar.high <= bar.low:
        return False
    close_location = (bar.close - bar.low) / (bar.high - bar.low)
    return bool(
        bar.close < bar.open
        and bar.close < row.ema20
        and bar.close < row.vwap
        and bar.close < row.previous_30m_low
        and row.rvol >= policy.rvol_severe
        and close_location <= Decimal("0.30")
    )


def recovered(previous: BarIndicators, current: BarIndicators) -> bool | None:
    if previous.ema20 is None or previous.vwap is None or current.ema20 is None or current.vwap is None:
        return None
    if not adjacent(previous.bar, current.bar):
        return False
    return bool(
        previous.bar.close > previous.ema20
        and previous.bar.close > previous.vwap
        and current.bar.close > current.ema20
        and current.bar.close > current.vwap
        and current.bar.low >= previous.bar.low
    )
