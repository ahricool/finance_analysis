# -*- coding: utf-8 -*-
"""Shared lot/position risk from daily bars and persisted stop state. Not a Strategy output."""

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


def _dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return coerce_aware_utc(value) or value
    return coerce_aware_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _dump_dec(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _dump_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = coerce_aware_utc(value) or value
    return aware.isoformat()


def fingerprint(lot_id: str, symbol: str, role: str, entry_price: Decimal, entry_time: datetime) -> str:
    aware = coerce_aware_utc(entry_time)
    return "|".join([lot_id, symbol, role, format(entry_price, "f"), aware.isoformat() if aware else ""])


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


def _ratchet_stage(stage: str, existing_stage: str | None) -> str:
    if existing_stage not in {STAGE_B, STAGE_C}:
        return stage
    if STAGE_ORDER.get(stage, 0) < STAGE_ORDER[existing_stage]:
        return existing_stage
    return stage


def update_lot_state(
    lot: ResolvedLot,
    existing: dict[str, Any] | None,
    bars: Sequence[DailyBar],
    policy: RiskPolicy,
    *,
    symbol: str,
) -> dict[str, Any]:
    mark = fingerprint(lot.lot_id, symbol, lot.role, lot.entry_price, lot.entry_time)
    entry_date = lot.entry_time.date()
    after = [bar for bar in bars if bar.trade_date >= entry_date]
    before = [bar for bar in bars if bar.trade_date < entry_date]
    observed_from = after[0].trade_date.isoformat() if after else None
    existing_high = _dec(existing.get("high_watermark")) if existing else None
    high = None
    high_date = None
    if after:
        high_bar = max(after, key=lambda bar: bar.close)
        high = high_bar.close
        high_date = high_bar.trade_date
        if existing_high is not None and existing_high > high:
            high = existing_high
            high_date = None
    elif existing_high is not None:
        high = existing_high
    m = None if high is None else (high / lot.entry_price) - Decimal("1")
    stage = _ratchet_stage(profit_stage(m, policy), existing.get("profit_stage") if existing else None)
    stored_structure = _dec(existing.get("structure_stop")) if existing else None
    structure = stored_structure if stored_structure is not None else structure_stop(before, lot.entry_price, policy)
    capital = capital_stop(lot.entry_price, policy)
    profit = profit_stop(lot.entry_price, high, stage, policy) if high is not None and stage in {STAGE_B, STAGE_C} else None
    previous_stop = _dec(existing.get("active_stop")) if existing else None
    active = _max_stop([capital, structure, profit, previous_stop])
    stop_effective_at = _dt(existing.get("stop_effective_at")) if existing else None
    if active is not None and (previous_stop is None or active > previous_stop):
        if high_date is not None:
            stop_effective_at = datetime(high_date.year, high_date.month, high_date.day, tzinfo=timezone.utc)
        elif after:
            last = after[-1].trade_date
            stop_effective_at = datetime(last.year, last.month, last.day, tzinfo=timezone.utc)
    if not after:
        coverage, coverage_reason = "NONE", "no_post_entry_daily_bars"
    else:
        coverage, coverage_reason = "FULL", None
    return {
        "lot_id": lot.lot_id,
        "role": lot.role,
        "entry_price": _dump_dec(lot.entry_price),
        "entry_time": _dump_dt(lot.entry_time),
        "input_fingerprint": mark,
        "last_quantity": _dump_dec(lot.quantity),
        "high_watermark": _dump_dec(high),
        "profit_stage": stage,
        "active_stop": _dump_dec(active),
        "structure_stop": _dump_dec(structure),
        "observed_from": observed_from,
        "coverage": coverage,
        "coverage_reason": coverage_reason,
        "stop_effective_at": _dump_dt(stop_effective_at),
    }


def position_stage(lot_state: dict[str, dict[str, Any]]) -> str:
    stages = [item.get("profit_stage") or "UNKNOWN" for item in lot_state.values()]
    if not stages:
        return "UNKNOWN"
    return max(stages, key=lambda item: STAGE_ORDER.get(item, 0))


def position_stop(lot_state: dict[str, dict[str, Any]]) -> Decimal | None:
    stops = [_dec(item.get("active_stop")) for item in lot_state.values()]
    stops = [item for item in stops if item is not None]
    return max(stops) if stops else None


def position_high(lot_state: dict[str, dict[str, Any]]) -> Decimal | None:
    highs = [_dec(item.get("high_watermark")) for item in lot_state.values()]
    highs = [item for item in highs if item is not None]
    return max(highs) if highs else None


def existing_position_risk(lots: Sequence[ResolvedLot], lot_state: dict[str, dict[str, Any]], price: Decimal) -> Decimal:
    total = Decimal("0")
    for lot in lots:
        if lot.quantity <= 0:
            continue
        stop = _dec((lot_state.get(lot.lot_id) or {}).get("active_stop"))
        if stop is None:
            continue
        gap = price - stop
        if gap > 0:
            total += lot.quantity * gap
    return total


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
    existing_state: dict[str, Any] | None,
    policy: RiskPolicy | None = None,
) -> tuple[PositionRisk, dict[str, dict[str, Any]]]:
    policy = policy or get_risk_policy()
    existing_lots = (existing_state or {}).get("lots") or {}
    lot_state = {
        lot.lot_id: update_lot_state(
            lot,
            existing_lots.get(lot.lot_id),
            bars,
            policy,
            symbol=position.symbol,
        )
        for lot in position.lots
    }
    lots = tuple(
        LotRisk(
            lot_id=lot.lot_id,
            role=lot.role,
            quantity=lot.quantity,
            entry_price=lot.entry_price,
            high_watermark=_dec(lot_state[lot.lot_id].get("high_watermark")),
            profit_stage=str(lot_state[lot.lot_id].get("profit_stage") or "UNKNOWN"),
            active_stop=_dec(lot_state[lot.lot_id].get("active_stop")),
            structure_stop=_dec(lot_state[lot.lot_id].get("structure_stop")),
        )
        for lot in position.lots
    )
    risk = PositionRisk(
        lots=lots,
        profit_stage=position_stage(lot_state),
        active_stop=position_stop(lot_state),
        high_watermark=position_high(lot_state),
        dump={
            "lots": lot_state,
            "profit_stage": position_stage(lot_state),
            "active_stop": _dump_dec(position_stop(lot_state)),
            "highest_confirmed_close": _dump_dec(position_high(lot_state)),
        },
    )
    return risk, lot_state
