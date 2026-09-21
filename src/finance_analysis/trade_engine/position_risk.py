# -*- coding: utf-8 -*-
"""Shared lot/position risk from Position + Lots + complete daily history. Stateless."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence

from ..core.time import coerce_aware_utc  # pragma: allowlist secret
from ..portfolio.models import ResolvedLot, ResolvedPosition  # pragma: allowlist secret
from .config import RiskPolicy, get_risk_policy  # pragma: allowlist secret
from .models import DailyBar, LotRisk, PositionRisk  # pragma: allowlist secret

STAGE_A = "A"
STAGE_B = "B"
STAGE_C = "C"
STAGE_ORDER = {"UNKNOWN": 0, STAGE_A: 1, STAGE_B: 2, STAGE_C: 3}


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _dump_dec(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _dump_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = coerce_aware_utc(value) or value
    return aware.isoformat()


def profit_stage(m: Decimal | None, policy: RiskPolicy) -> str:
    if m is None:
        return "UNKNOWN"
    if m < policy.stage_a_max:
        return STAGE_A
    if m < policy.stage_b_max:
        return STAGE_B
    return STAGE_C


def capital_stop(entry: Decimal, policy: RiskPolicy) -> Decimal:
    return entry * (Decimal("1") - policy.capital_stop)


def profit_stop(entry: Decimal, high: Decimal, stage: str, policy: RiskPolicy) -> Decimal | None:
    if stage == STAGE_B:
        return entry + policy.stage_b_lock * (high - entry)
    if stage == STAGE_C:
        return entry + policy.stage_c_lock * (high - entry)
    return None


def structure_stop(bars_before: Sequence[DailyBar], entry: Decimal, policy: RiskPolicy) -> Decimal | None:
    if len(bars_before) < policy.structure_bars:
        return None
    window = list(bars_before)[-policy.structure_bars :]
    stop = min(bar.low for bar in window)
    if stop <= 0 or stop >= entry:
        return None
    return stop


def _max_stop(candidates: Sequence[Decimal | None]) -> Decimal | None:
    valid = [item for item in candidates if item is not None]
    return max(valid) if valid else None


def _lot_risk(lot: ResolvedLot, bars: Sequence[DailyBar], policy: RiskPolicy) -> LotRisk:
    entry_date = lot.entry_time.date()
    after = [bar for bar in bars if bar.trade_date >= entry_date]
    before = [bar for bar in bars if bar.trade_date < entry_date]
    high = None
    high_date = None
    if after:
        high_bar = max(after, key=lambda bar: bar.close)
        high = high_bar.close
        high_date = high_bar.trade_date
    m = None if high is None else (high / lot.entry_price) - Decimal("1")
    stage = profit_stage(m, policy)
    structure = structure_stop(before, lot.entry_price, policy)
    capital = capital_stop(lot.entry_price, policy)
    profit = profit_stop(lot.entry_price, high, stage, policy) if high is not None and stage in {STAGE_B, STAGE_C} else None
    active = _max_stop([capital, structure, profit])
    if high_date is not None:
        stop_effective_at = datetime(high_date.year, high_date.month, high_date.day, tzinfo=timezone.utc)
    else:
        stop_effective_at = coerce_aware_utc(lot.entry_time)
    return LotRisk(
        lot_id=lot.lot_id,
        role=lot.role,
        quantity=lot.quantity,
        entry_price=lot.entry_price,
        high_watermark=high,
        profit_stage=stage,
        active_stop=active,
        structure_stop=structure,
        stop_effective_at=stop_effective_at,
    )


def position_stage(lots: Sequence[LotRisk]) -> str:
    stages = [item.profit_stage or "UNKNOWN" for item in lots]
    if not stages:
        return "UNKNOWN"
    return max(stages, key=lambda item: STAGE_ORDER.get(item, 0))


def position_stop(lots: Sequence[LotRisk]) -> Decimal | None:
    stops = [item.active_stop for item in lots if item.active_stop is not None]
    return max(stops) if stops else None


def position_high(lots: Sequence[LotRisk]) -> Decimal | None:
    highs = [item.high_watermark for item in lots if item.high_watermark is not None]
    return max(highs) if highs else None


def open_position_risk(risk: PositionRisk, price: Decimal) -> Decimal:
    """Per-lot open risk. CORE and ADDON stops are never collapsed to one max stop."""

    total = Decimal("0")
    for lot in risk.lots:
        if lot.active_stop is None:
            continue
        total += lot.quantity * max(price - lot.active_stop, Decimal("0"))
    return total


def compute_position_risk(
    position: ResolvedPosition,
    bars: Sequence[DailyBar],
    policy: RiskPolicy | None = None,
) -> PositionRisk:
    policy = policy or get_risk_policy()
    lots = tuple(_lot_risk(lot, bars, policy) for lot in position.lots)
    dump_lots = {
        lot.lot_id: {
            "lot_id": lot.lot_id,
            "role": lot.role,
            "entry_price": _dump_dec(lot.entry_price),
            "high_watermark": _dump_dec(lot.high_watermark),
            "profit_stage": lot.profit_stage,
            "active_stop": _dump_dec(lot.active_stop),
            "structure_stop": _dump_dec(lot.structure_stop),
            "stop_effective_at": _dump_dt(lot.stop_effective_at),
        }
        for lot in lots
    }
    return PositionRisk(
        lots=lots,
        profit_stage=position_stage(lots),
        active_stop=position_stop(lots),
        high_watermark=position_high(lots),
        dump={
            "lots": dump_lots,
            "profit_stage": position_stage(lots),
            "active_stop": _dump_dec(position_stop(lots)),
            "highest_confirmed_close": _dump_dec(position_high(lots)),
        },
    )
