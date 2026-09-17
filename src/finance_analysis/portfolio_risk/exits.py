# -*- coding: utf-8 -*-
"""Position-level exit planning. Hard stops per leg; soft weakness is one shared plan."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Sequence
from uuid import uuid4

from finance_analysis.portfolio_risk.bars import NormalizedBar  # pragma: allowlist secret
from finance_analysis.portfolio_risk.config import RiskPolicy  # pragma: allowlist secret
from finance_analysis.portfolio_risk.indicators import (  # pragma: allowlist secret
    annotate,
    ordinary_weak,
    recovered,
    severe_break,
)
from finance_analysis.portfolio_risk.models import (  # pragma: allowlist secret
    Action,
    ActivePlan,
    LegRiskState,
    fingerprint,
)

STAGE_A = "A"
STAGE_B = "B"
STAGE_C = "C"


@dataclass(frozen=True, slots=True)
class QuoteView:
    price: Decimal
    quote_as_of: datetime | None
    valid: bool
    stale: bool = False


@dataclass(frozen=True, slots=True)
class LegInput:
    leg_id: str
    role: str
    quantity: Decimal
    entry_price: Decimal
    entry_time: datetime
    initial_stop: Decimal | None = None
    coverage: str = "COVERED"


@dataclass(frozen=True, slots=True)
class PositionInput:
    account_id: str
    position_id: str
    symbol: str
    legs: tuple[LegInput, ...]


@dataclass(frozen=True, slots=True)
class PositionState:
    row_version: int = 1
    rule_version: str = "v1"
    weak_streak: int = 0
    recovery_streak: int = 0
    episode_id: str | None = None
    last_bar_end: datetime | None = None
    last_vwap_mode: str | None = None
    plan: ActivePlan = field(default_factory=ActivePlan)
    legs: dict[str, LegRiskState] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LegExit:
    leg_id: str
    target_quantity: Decimal
    reason: str
    action: Action
    stage: str
    active_stop: Decimal | None
    hard_exit: bool = False


@dataclass(frozen=True, slots=True)
class PositionExitResult:
    action: Action
    plan: ActivePlan
    state: PositionState
    leg_exits: tuple[LegExit, ...]
    position_target: Decimal
    reduce_quantity: Decimal
    reasons: tuple[str, ...]
    events: tuple[dict, ...]
    evidence: dict
    evaluated_bar_end: datetime | None
    quote_as_of: datetime | None
    five_minute_status: str
    quote_status: str


def _stage(m: Decimal | None, policy: RiskPolicy) -> str:
    if m is None:
        return "UNKNOWN"
    if m < policy.stage_a_max:
        return STAGE_A
    if m < policy.stage_b_max:
        return STAGE_B
    return STAGE_C


def _capital_stop(entry: Decimal, policy: RiskPolicy) -> Decimal:
    return entry * (Decimal("1") - policy.capital_stop)


def _profit_stop(entry: Decimal, high: Decimal, stage: str, policy: RiskPolicy) -> Decimal | None:
    if stage == STAGE_B:
        return entry + policy.stage_b_lock * (high - entry)
    if stage == STAGE_C:
        return entry + policy.stage_c_lock * (high - entry)
    return None


def _valid_price(value: Decimal | None, *, entry: Decimal) -> Decimal | None:
    if value is None or value <= 0:
        return None
    if value > entry * Decimal("10"):
        return None
    return value


def _structure_stop(bars_before: Sequence[NormalizedBar], entry: Decimal, policy: RiskPolicy) -> Decimal | None:
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


def _update_leg_baselines(
    leg: LegInput,
    existing: LegRiskState | None,
    bars: Sequence[NormalizedBar],
    policy: RiskPolicy,
    *,
    symbol: str,
) -> LegRiskState:
    mark = fingerprint(leg.leg_id, symbol, leg.role, leg.entry_price, leg.entry_time)
    if existing is not None and existing.input_fingerprint != mark:
        return existing.model_copy(update={"calibration_required": True, "last_quantity": leg.quantity})
    after = [bar for bar in bars if bar.closed and bar.bar_end > leg.entry_time]
    before = [bar for bar in bars if bar.closed and bar.bar_end <= leg.entry_time]
    observed_from = after[0].bar_end if after else None
    high = None
    if after:
        high = max(bar.close for bar in after)
        if existing and existing.high_watermark is not None:
            high = max(high, existing.high_watermark)
    elif existing and existing.high_watermark is not None:
        high = existing.high_watermark
    m = None if high is None else (high / leg.entry_price) - Decimal("1")
    stage = _stage(m, policy)
    if existing and existing.profit_stage in {STAGE_B, STAGE_C}:
        order = {"UNKNOWN": 0, STAGE_A: 1, STAGE_B: 2, STAGE_C: 3}
        if order.get(stage, 0) < order[existing.profit_stage]:
            stage = existing.profit_stage
    structure = existing.structure_stop if existing and existing.structure_stop is not None else None
    if structure is None and leg.role == "ADDON":
        structure = _structure_stop(before, leg.entry_price, policy)
    capital = _capital_stop(leg.entry_price, policy)
    profit = _profit_stop(leg.entry_price, high, stage, policy) if high is not None and stage in {STAGE_B, STAGE_C} else None
    initial = _valid_price(leg.initial_stop, entry=leg.entry_price)
    previous_stop = existing.active_stop if existing else None
    active = _max_stop([capital, initial, structure, profit, previous_stop])
    coverage = "FULL" if after and len(after) >= policy.ema_warmup else ("PARTIAL" if after else "NONE")
    return LegRiskState(
        leg_id=leg.leg_id,
        role=leg.role,
        entry_price=leg.entry_price,
        entry_time=leg.entry_time,
        input_fingerprint=mark,
        last_quantity=leg.quantity,
        high_watermark=high,
        profit_stage=stage,
        active_stop=active,
        structure_stop=structure,
        observed_from=observed_from,
        coverage=coverage,
        fixed_target=existing.fixed_target if existing else None,
        calibration_required=bool(existing.calibration_required) if existing else False,
    )


def evaluate_position_exit(
    position: PositionInput,
    *,
    quote: QuoteView | None,
    bars: Sequence[NormalizedBar],
    state: PositionState,
    policy: RiskPolicy,
    now: datetime,
    market: str,
) -> PositionExitResult:
    annotated = annotate(bars, policy=policy, market=market, now=now)
    closed = [row for row in annotated if row.bar.closed]
    unprocessed = [row for row in closed if state.last_bar_end is None or row.bar.bar_end > state.last_bar_end]
    legs_state = {
        leg.leg_id: _update_leg_baselines(
            leg, state.legs.get(leg.leg_id), [row.bar for row in closed], policy, symbol=position.symbol
        )
        for leg in position.legs
    }
    events: list[dict] = []
    reasons: list[str] = []
    quote_status = "UNAVAILABLE"
    if quote is None:
        quote_status = "UNAVAILABLE"
    elif quote.quote_as_of is None:
        quote_status = "UNKNOWN_TIME"
    elif quote.stale:
        quote_status = "STALE"
    elif not quote.valid:
        quote_status = "UNAVAILABLE"
    else:
        quote_status = "OK"

    hard_targets: dict[str, Decimal] = {leg.leg_id: leg.quantity for leg in position.legs}
    hard_reasons: dict[str, str] = {}
    if quote_status == "OK" and quote is not None:
        for leg in position.legs:
            stop = legs_state[leg.leg_id].active_stop
            if stop is not None and quote.price < stop and not legs_state[leg.leg_id].calibration_required:
                hard_targets[leg.leg_id] = Decimal("0")
                hard_reasons[leg.leg_id] = "hard_stop"
                reasons.append(f"{leg.leg_id}:报价低于保护价")

    five_status = "OK" if unprocessed or (closed and state.last_bar_end == closed[-1].bar.bar_end) else "UNAVAILABLE"
    if not closed:
        five_status = "UNAVAILABLE"
    elif unprocessed and any(row.gap_before for row in unprocessed):
        five_status = "GAP"

    plan = state.plan
    weak_streak = state.weak_streak
    recovery_streak = state.recovery_streak
    episode_id = state.episode_id
    last_vwap = state.last_vwap_mode
    last_bar_end = state.last_bar_end
    action: Action = "HOLD"
    new_soft = False
    severe = False

    if five_status != "UNAVAILABLE":
        for row in unprocessed:
            if last_vwap and row.vwap_mode != last_vwap:
                weak_streak = 0
                recovery_streak = 0
            last_vwap = row.vwap_mode
            if row.gap_before:
                weak_streak = 0
                recovery_streak = 0
            last_bar_end = row.bar.bar_end
            if row.opening_observation:
                continue
            weak = ordinary_weak(row, policy)
            is_severe = severe_break(row, policy)
            if is_severe is True:
                severe = True
                new_soft = True
                weak_streak = 2
                recovery_streak = 0
                if episode_id is None:
                    episode_id = uuid4().hex
                action = "EXIT"
                reasons.append("严重破位单根确认")
                continue
            if weak is True:
                weak_streak = 1 if weak_streak <= 0 else weak_streak + 1
                recovery_streak = 0
                if weak_streak == 1:
                    action = "WATCH"
                    reasons.append("普通走弱观察")
                elif weak_streak >= 2:
                    new_soft = True
                    if episode_id is None:
                        episode_id = uuid4().hex
                    action = "REDUCE"
                    reasons.append("相邻两根确认走弱")
            elif weak is False:
                weak_streak = 0
            if len(closed) >= 2:
                rec = recovered(closed[-2], closed[-1]) if row is closed[-1] else None
                if rec is True:
                    recovery_streak += 1
                else:
                    recovery_streak = 0
                if recovery_streak >= 2 and episode_id and plan.status == "PENDING":
                    reasons.append("行情恢复但计划未完成")
                    recovery_streak = 0
                    episode_id = None
                    weak_streak = 0

    remaining = {leg.leg_id: hard_targets[leg.leg_id] for leg in position.legs}
    if plan.status == "PENDING" and plan.leg_targets:
        for leg_id, target in plan.leg_targets.items():
            if leg_id in remaining:
                remaining[leg_id] = min(remaining[leg_id], Decimal(target))

    if new_soft and plan.status == "PENDING":
        reasons.append("同一episode保持固定目标")
    elif new_soft:
        addon_fail = [
            leg
            for leg in position.legs
            if leg.role == "ADDON"
            and legs_state[leg.leg_id].profit_stage == STAGE_A
            and remaining[leg.leg_id] > 0
            and leg.entry_time <= (unprocessed[-1].bar.bar_end if unprocessed else now)
        ]
        if addon_fail:
            for leg in addon_fail:
                remaining[leg.leg_id] = Decimal("0")
                reasons.append(f"{leg.leg_id}:未站稳加仓优先清零")
        else:
            stage_a = [leg for leg in position.legs if legs_state[leg.leg_id].profit_stage == STAGE_A]
            for leg in stage_a:
                remaining[leg.leg_id] = Decimal("0")
            profitable = [
                leg
                for leg in position.legs
                if legs_state[leg.leg_id].profit_stage in {STAGE_B, STAGE_C} and remaining[leg.leg_id] > 0
            ]
            budget = sum((remaining[leg.leg_id] for leg in profitable), start=Decimal("0")) * Decimal("0.5")
            for leg in sorted(profitable, key=lambda item: item.entry_time, reverse=True):
                if budget <= 0:
                    break
                take = min(remaining[leg.leg_id], budget)
                remaining[leg.leg_id] -= take
                budget -= take
        plan = ActivePlan(
            revision=plan.revision + 1,
            status="PENDING",
            action="EXIT" if severe or all(value == 0 for value in remaining.values()) else "REDUCE",
            episode_id=episode_id,
            bound_leg_ids=[leg.leg_id for leg in position.legs],
            leg_targets={leg_id: format(qty, "f") for leg_id, qty in remaining.items()},
            position_target=format(sum(remaining.values(), start=Decimal("0")), "f"),
            reason=";".join(reasons) or "soft_exit",
            created_bar_end=unprocessed[-1].bar.bar_end if unprocessed else None,
            execution="UNKNOWN",
        )
        events.append(
            {
                "event_type": "SEVERE_BREAK" if severe else "CONFIRMED_WEAK",
                "action": plan.action,
                "episode_id": episode_id,
                "plan_revision": plan.revision,
            }
        )
    elif hard_reasons and plan.status != "PENDING":
        plan = ActivePlan(
            revision=plan.revision + 1,
            status="PENDING",
            action="EXIT",
            episode_id=episode_id,
            bound_leg_ids=list(hard_reasons),
            leg_targets={leg_id: format(qty, "f") for leg_id, qty in remaining.items()},
            position_target=format(sum(remaining.values(), start=Decimal("0")), "f"),
            reason="hard_stop",
            created_bar_end=last_bar_end,
            execution="UNKNOWN",
        )
        events.append({"event_type": "HARD_STOP", "action": "EXIT", "episode_id": episode_id, "plan_revision": plan.revision})

    current_qty = sum((leg.quantity for leg in position.legs), start=Decimal("0"))
    target = sum(remaining.values(), start=Decimal("0"))
    if plan.status == "PENDING" and current_qty <= Decimal(plan.position_target or target):
        plan = plan.model_copy(update={"status": "SATISFIED_BY_SHEET"})
        events.append({"event_type": "PLAN_SATISFIED", "action": plan.action, "episode_id": episode_id, "plan_revision": plan.revision})

    if quote_status != "OK" and hard_reasons:
        pass
    if quote_status != "OK":
        reasons.append("报价无效时不更新实时触发，已有EXIT不自动解除")

    leg_exits = tuple(
        LegExit(
            leg_id=leg.leg_id,
            target_quantity=remaining[leg.leg_id],
            reason=hard_reasons.get(leg.leg_id) or (plan.reason or "hold"),
            action="EXIT" if remaining[leg.leg_id] == 0 and leg.quantity > 0 else plan.action,
            stage=legs_state[leg.leg_id].profit_stage,
            active_stop=legs_state[leg.leg_id].active_stop,
            hard_exit=leg.leg_id in hard_reasons,
        )
        for leg in position.legs
    )
    next_state = replace(
        state,
        weak_streak=weak_streak,
        recovery_streak=recovery_streak,
        episode_id=episode_id,
        last_bar_end=last_bar_end,
        last_vwap_mode=last_vwap,
        plan=plan,
        legs=legs_state,
        rule_version=policy.rule_version,
    )
    evidence = {}
    if unprocessed:
        row = unprocessed[-1]
        evidence = {
            "bar_end": row.bar.bar_end.isoformat(),
            "close": format(row.bar.close, "f"),
            "ema20": None if row.ema20 is None else format(row.ema20, "f"),
            "vwap": None if row.vwap is None else format(row.vwap, "f"),
            "vwap_mode": row.vwap_mode,
            "previous_30m_low": None if row.previous_30m_low is None else format(row.previous_30m_low, "f"),
            "rvol": None if row.rvol is None else format(row.rvol, "f"),
            "rule_version": policy.rule_version,
        }
    return PositionExitResult(
        action=plan.action if plan.status == "PENDING" else action,
        plan=plan,
        state=next_state,
        leg_exits=leg_exits,
        position_target=target,
        reduce_quantity=max(Decimal("0"), current_qty - target),
        reasons=tuple(reasons),
        events=tuple(events),
        evidence=evidence,
        evaluated_bar_end=last_bar_end,
        quote_as_of=None if quote is None else quote.quote_as_of,
        five_minute_status=five_status,
        quote_status=quote_status,
    )
