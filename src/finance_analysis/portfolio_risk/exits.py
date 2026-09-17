# -*- coding: utf-8 -*-
"""Position-level exit planning. Hard stops per leg; soft weakness is one shared plan."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Sequence
from uuid import uuid4

from .bars import NormalizedBar, adjacent, expected_closed_ends, latest_expected_closed
from .config import RiskPolicy
from .indicators import annotate, ordinary_weak, recovered, severe_break
from .models import Action, ActivePlan, LegRiskState, fingerprint

STAGE_A = "A"
STAGE_B = "B"
STAGE_C = "C"
QUOTE_FUTURE_SKEW = timedelta(seconds=5)


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
    available_quantity: Decimal | None = None
    available_as_of: datetime | None = None


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
    episode_consumed: bool = False
    needs_review: bool = False
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
    needs_review: bool = False
    episode_consumed: bool = False
    latest_expected_closed: datetime | None = None
    bars_stale: bool = False


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


def _covered(leg: LegInput) -> bool:
    return (leg.coverage or "COVERED") == "COVERED"


def _quote_status(quote: QuoteView | None, now: datetime) -> str:
    if quote is None:
        return "UNAVAILABLE"
    if quote.quote_as_of is None:
        return "UNKNOWN_TIME"
    if quote.quote_as_of > now + QUOTE_FUTURE_SKEW:
        return "FUTURE"
    if quote.stale:
        return "STALE"
    if not quote.valid:
        return "UNAVAILABLE"
    return "OK"


def _plan_action(remaining: dict[str, Decimal], current_qty: Decimal) -> Action:
    target = sum(remaining.values(), start=Decimal("0"))
    if target <= 0 and current_qty > 0:
        return "EXIT"
    if target < current_qty:
        return "REDUCE"
    return "HOLD"


def _evidence(row) -> dict:
    if row is None:
        return {}
    return {
        "bar_end": row.bar.bar_end.isoformat(),
        "close": format(row.bar.close, "f"),
        "ema20": None if row.ema20 is None else format(row.ema20, "f"),
        "vwap": None if row.vwap is None else format(row.vwap, "f"),
        "vwap_mode": row.vwap_mode,
        "previous_30m_low": None if row.previous_30m_low is None else format(row.previous_30m_low, "f"),
        "rvol": None if row.rvol is None else format(row.rvol, "f"),
    }


def _update_leg_baselines(
    leg: LegInput,
    existing: LegRiskState | None,
    bars: Sequence[NormalizedBar],
    policy: RiskPolicy,
    *,
    symbol: str,
    market: str,
) -> LegRiskState:
    mark = fingerprint(leg.leg_id, symbol, leg.role, leg.entry_price, leg.entry_time)
    if existing is not None and existing.input_fingerprint != mark:
        return existing.model_copy(update={"calibration_required": True, "last_quantity": leg.quantity})
    after = [bar for bar in bars if bar.closed and bar.bar_end > leg.entry_time]
    before = [bar for bar in bars if bar.closed and bar.bar_end <= leg.entry_time]
    observed_from = after[0].bar_end if after else None
    high = None
    high_bar_end = None
    if after:
        high_bar = max(after, key=lambda bar: bar.close)
        high = high_bar.close
        high_bar_end = high_bar.bar_end
        if existing and existing.high_watermark is not None:
            if existing.high_watermark > high:
                high = existing.high_watermark
                high_bar_end = existing.stop_effective_at or high_bar_end
    elif existing and existing.high_watermark is not None:
        high = existing.high_watermark
        high_bar_end = existing.stop_effective_at
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
    previous = existing.active_stop if existing else None
    stop_effective_at = existing.stop_effective_at if existing else None
    if active is not None and (previous is None or active > previous):
        stop_effective_at = high_bar_end or (after[-1].bar_end if after else None)
    last_end = after[-1].bar_end if after else None
    expected = expected_closed_ends(market, leg.entry_time, last_end) if last_end is not None else []
    present_ends = {bar.bar_end for bar in after}
    if not after:
        coverage, coverage_reason = "NONE", "no_post_entry_bars"
    elif expected and present_ends >= set(expected):
        coverage, coverage_reason = "FULL", None
    else:
        coverage, coverage_reason = "PARTIAL", "high_watermark_coverage_incomplete"
    rebase_status = existing.rebase_status if existing else "NONE"
    if existing and existing.rebase_status == "PENDING_CONFIRM" and existing.input_fingerprint == mark:
        rebase_status = "CONFIRMED"
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
        coverage_reason=coverage_reason,
        fixed_target=existing.fixed_target if existing else None,
        calibration_required=bool(existing.calibration_required) if existing else False,
        stop_effective_at=stop_effective_at,
        rebase_status=rebase_status,
    )


def _make_plan(
    *,
    previous: ActivePlan,
    remaining: dict[str, Decimal],
    current_qty: Decimal,
    episode_id: str | None,
    bound_leg_ids: list[str],
    reason: str,
    created_bar_end: datetime | None,
    hard_locked: bool,
    trigger_event: str,
    execution: str = "UNKNOWN",
    needs_review: bool = False,
) -> ActivePlan:
    action = _plan_action(remaining, current_qty)
    target = sum(remaining.values(), start=Decimal("0"))
    return ActivePlan(
        revision=previous.revision + 1,
        status="PENDING",
        action=action,
        episode_id=episode_id,
        bound_leg_ids=bound_leg_ids,
        leg_targets={leg_id: format(qty, "f") for leg_id, qty in remaining.items()},
        position_target=format(target, "f"),
        current_quantity=format(current_qty, "f"),
        reduce_quantity=format(max(Decimal("0"), current_qty - target), "f"),
        reason=reason,
        created_bar_end=created_bar_end,
        execution=execution,
        hard_locked=hard_locked,
        needs_review=needs_review,
        trigger_event=trigger_event,
    )


def _bound_quantities(position: PositionInput, plan: ActivePlan) -> tuple[Decimal, Decimal, bool]:
    bound = set(plan.bound_leg_ids or [leg.leg_id for leg in position.legs])
    current = Decimal("0")
    target = Decimal("0")
    matched = True
    by_id = {leg.leg_id: leg.quantity for leg in position.legs}
    for leg_id in bound:
        qty = by_id.get(leg_id)
        if qty is None:
            matched = False
            continue
        current += qty
        planned = plan.leg_targets.get(leg_id)
        if planned is None:
            matched = False
            continue
        target += Decimal(planned)
    total_current = sum((leg.quantity for leg in position.legs if leg.leg_id in bound), start=Decimal("0"))
    return total_current, target, matched


def evaluate_position_exit(
    position: PositionInput,
    *,
    quote: QuoteView | None,
    bars: Sequence[NormalizedBar],
    state: PositionState,
    policy: RiskPolicy,
    now: datetime,
    market: str,
    latest_expected: datetime | None = None,
    bars_stale: bool = False,
    holdings_actionable: bool = True,
) -> PositionExitResult:
    annotated = annotate(bars, policy=policy, market=market, now=now)
    closed = [row for row in annotated if row.bar.closed]
    expected = latest_expected if latest_expected is not None else latest_expected_closed(market, now)
    legs_state = {
        leg.leg_id: _update_leg_baselines(
            leg, state.legs.get(leg.leg_id), [row.bar for row in closed], policy, symbol=position.symbol, market=market
        )
        for leg in position.legs
    }
    events: list[dict] = []
    reasons: list[str] = []
    quote_status = _quote_status(quote, now)
    trigger_row = None

    earliest_entry = min((leg.entry_time for leg in position.legs), default=now)
    hard_targets: dict[str, Decimal] = {leg.leg_id: leg.quantity for leg in position.legs}
    hard_reasons: dict[str, str] = {}
    if quote_status == "OK" and quote is not None:
        for leg in position.legs:
            if not _covered(leg) or legs_state[leg.leg_id].calibration_required:
                continue
            stop = legs_state[leg.leg_id].active_stop
            effective = legs_state[leg.leg_id].stop_effective_at
            if stop is None:
                continue
            if effective is not None and quote.quote_as_of is not None and effective > quote.quote_as_of:
                continue
            if quote.price <= stop:
                hard_targets[leg.leg_id] = Decimal("0")
                hard_reasons[leg.leg_id] = "hard_stop"
                reasons.append(f"{leg.leg_id}:报价触及保护价")

    five_status = "UNAVAILABLE"
    if not closed:
        five_status = "UNAVAILABLE"
    elif bars_stale:
        five_status = "STALE"
    else:
        last_end = closed[-1].bar.bar_end
        if expected is not None and last_end < expected:
            five_status = "STALE"
        else:
            five_status = "OK"

    plan = state.plan
    if plan.hard_locked and Decimal(plan.position_target or "0") <= 0:
        for leg in position.legs:
            hard_targets[leg.leg_id] = min(hard_targets[leg.leg_id], Decimal("0"))

    remaining = dict(hard_targets)
    if plan.status == "PENDING" and plan.leg_targets:
        for leg_id, target in plan.leg_targets.items():
            if leg_id in remaining:
                remaining[leg_id] = min(remaining[leg_id], Decimal(target))

    weak_streak = state.weak_streak
    recovery_streak = state.recovery_streak
    episode_id = state.episode_id
    episode_consumed = state.episode_consumed
    needs_review = state.needs_review or plan.needs_review
    last_vwap = state.last_vwap_mode
    last_bar_end = state.last_bar_end
    restoring = state.last_bar_end is None
    allow_soft = five_status == "OK" and not bars_stale
    action: Action = "HOLD"
    new_soft = False
    severe = False
    soft_trigger = None

    decision_rows = []
    if allow_soft:
        for row in closed:
            if last_bar_end is not None and row.bar.bar_end <= last_bar_end:
                continue
            if row.bar.bar_end <= earliest_entry:
                last_bar_end = row.bar.bar_end
                continue
            decision_rows.append(row)

    previous_row = None
    if decision_rows:
        prior = [row for row in closed if row.bar.bar_end < decision_rows[0].bar.bar_end]
        previous_row = prior[-1] if prior else None

    for row in decision_rows:
        if last_vwap and row.vwap_mode != last_vwap:
            weak_streak = 0
            recovery_streak = 0
        last_vwap = row.vwap_mode
        if row.gap_before:
            weak_streak = 0
            recovery_streak = 0
        last_bar_end = row.bar.bar_end
        if row.opening_observation:
            previous_row = row
            continue
        is_current = expected is not None and row.bar.bar_end == expected
        can_emit = holdings_actionable and (not restoring or is_current) and is_current
        weak = ordinary_weak(row, policy)
        is_severe = severe_break(row, policy)
        if is_severe is True:
            weak_streak = 2
            recovery_streak = 0
            if can_emit and not episode_consumed:
                severe = True
                new_soft = True
                if episode_id is None:
                    episode_id = uuid4().hex
                action = "WATCH"
                reasons.append("严重破位单根确认")
                soft_trigger = row
            previous_row = row
            continue
        if weak is True:
            if previous_row is not None and adjacent(previous_row.bar, row.bar) and weak_streak >= 1:
                weak_streak += 1
            else:
                weak_streak = 1
            recovery_streak = 0
            if weak_streak == 1:
                action = "WATCH"
                reasons.append("普通走弱观察")
            elif weak_streak >= 2 and can_emit and not episode_consumed:
                new_soft = True
                if episode_id is None:
                    episode_id = uuid4().hex
                reasons.append("相邻两根确认走弱")
                soft_trigger = row
        elif weak is False:
            weak_streak = 0
        else:
            weak_streak = 0
        if previous_row is not None:
            rec = recovered(previous_row, row)
            if rec is True:
                recovery_streak += 1
            else:
                recovery_streak = 0
            if recovery_streak >= 2 and episode_id:
                events.append(
                    {
                        "event_type": "EPISODE_RECOVERED",
                        "action": "HOLD",
                        "episode_id": episode_id,
                        "plan_revision": plan.revision,
                    }
                )
                reasons.append("相邻两根确认恢复")
                episode_id = None
                episode_consumed = False
                weak_streak = 0
                recovery_streak = 0
        previous_row = row

    if new_soft and plan.status in {"SATISFIED_BY_SHEET", "CANCELED"}:
        new_soft = False
        reasons.append("本episode软退出已消费")
    if new_soft and episode_consumed:
        new_soft = False
        reasons.append("同一episode不再重复软减仓")
    if new_soft and plan.status == "PENDING" and not plan.hard_locked:
        new_soft = False
        reasons.append("同一episode保持固定目标")

    if new_soft:
        trigger_row = soft_trigger or (decision_rows[-1] if decision_rows else None)
        trigger_end = trigger_row.bar.bar_end if trigger_row is not None else expected
        addon_fail = [
            leg
            for leg in position.legs
            if _covered(leg)
            and leg.role == "ADDON"
            and legs_state[leg.leg_id].profit_stage == STAGE_A
            and remaining[leg.leg_id] > 0
            and trigger_end is not None
            and leg.entry_time < trigger_end
        ]
        if addon_fail:
            for leg in addon_fail:
                remaining[leg.leg_id] = Decimal("0")
                reasons.append(f"{leg.leg_id}:未站稳加仓优先清零")
        else:
            stage_a = [leg for leg in position.legs if _covered(leg) and legs_state[leg.leg_id].profit_stage == STAGE_A]
            for leg in stage_a:
                remaining[leg.leg_id] = Decimal("0")
            profitable = [
                leg
                for leg in position.legs
                if _covered(leg)
                and legs_state[leg.leg_id].profit_stage in {STAGE_B, STAGE_C}
                and remaining[leg.leg_id] > 0
            ]
            budget = sum((remaining[leg.leg_id] for leg in profitable), start=Decimal("0")) * Decimal("0.5")
            for leg in sorted(profitable, key=lambda item: item.entry_time, reverse=True):
                if budget <= 0:
                    break
                take = min(remaining[leg.leg_id], budget)
                remaining[leg.leg_id] -= take
                budget -= take
        current_qty = sum((leg.quantity for leg in position.legs), start=Decimal("0"))
        plan = _make_plan(
            previous=plan,
            remaining=remaining,
            current_qty=current_qty,
            episode_id=episode_id,
            bound_leg_ids=[leg.leg_id for leg in position.legs],
            reason=";".join(reasons) or "soft_exit",
            created_bar_end=trigger_end,
            hard_locked=False,
            trigger_event="SEVERE_BREAK" if severe else "CONFIRMED_WEAK",
        )
        episode_consumed = True
        events.append(
            {
                "event_type": "SEVERE_BREAK" if severe else "CONFIRMED_WEAK",
                "action": plan.action,
                "episode_id": episode_id,
                "plan_revision": plan.revision,
            }
        )

    current_qty = sum((leg.quantity for leg in position.legs), start=Decimal("0"))
    hard_upgrade = bool(hard_reasons) and holdings_actionable
    if hard_upgrade:
        if plan.hard_locked and Decimal(plan.position_target or "0") <= 0:
            remaining = {leg.leg_id: Decimal("0") for leg in position.legs}
        target = sum(remaining.values(), start=Decimal("0"))
        previous_target = Decimal(plan.position_target) if plan.status == "PENDING" and plan.position_target else current_qty
        should_upgrade = plan.status != "PENDING" or target < previous_target or plan.hard_locked
        if should_upgrade:
            already = plan.trigger_event == "HARD_STOP" and plan.status == "PENDING" and target == previous_target
            if not already:
                plan = _make_plan(
                    previous=plan,
                    remaining=remaining,
                    current_qty=current_qty,
                    episode_id=episode_id,
                    bound_leg_ids=list(hard_reasons) or [leg.leg_id for leg in position.legs],
                    reason="hard_stop",
                    created_bar_end=last_bar_end,
                    hard_locked=target <= 0,
                    trigger_event="HARD_STOP",
                )
                events.append(
                    {
                        "event_type": "HARD_STOP",
                        "action": plan.action,
                        "episode_id": episode_id,
                        "plan_revision": plan.revision,
                    }
                )

    if plan.status == "PENDING":
        bound_current, bound_target, matched = _bound_quantities(position, plan)
        extra_open = [leg for leg in position.legs if leg.leg_id not in set(plan.bound_leg_ids or [])]
        if extra_open:
            reasons.append("新增腿不改变已绑定计划")
        if bound_current <= bound_target:
            if matched:
                plan = plan.model_copy(update={"status": "SATISFIED_BY_SHEET"})
                events.append(
                    {
                        "event_type": "PLAN_SATISFIED",
                        "action": plan.action,
                        "episode_id": episode_id,
                        "plan_revision": plan.revision,
                    }
                )
                episode_consumed = True
            else:
                needs_review = True
                plan = plan.model_copy(update={"needs_review": True})
                events.append(
                    {
                        "event_type": "PLAN_NEEDS_REVIEW",
                        "action": plan.action,
                        "episode_id": episode_id,
                        "plan_revision": plan.revision,
                    }
                )
                episode_consumed = True
                reasons.append("总量已减够但腿归因不一致，待核对")

    if quote_status != "OK":
        reasons.append("报价无效时不更新实时触发，已有EXIT不自动解除")

    for leg in position.legs:
        if legs_state[leg.leg_id].rebase_status == "CONFIRMED" and (
            state.legs.get(leg.leg_id) is None or state.legs[leg.leg_id].rebase_status != "CONFIRMED"
        ):
            events.append(
                {
                    "event_type": "REBASE_CONFIRMED",
                    "action": "HOLD",
                    "episode_id": episode_id,
                    "plan_revision": plan.revision,
                    "leg_id": leg.leg_id,
                }
            )

    target = sum(remaining.values(), start=Decimal("0"))
    result_action = plan.action if plan.status == "PENDING" else action
    if plan.status == "PENDING" and target > 0 and result_action == "EXIT":
        result_action = "REDUCE"
        plan = plan.model_copy(update={"action": "REDUCE"})
    if plan.status == "PENDING":
        plan = plan.model_copy(
            update={
                "current_quantity": format(current_qty, "f"),
                "reduce_quantity": format(max(Decimal("0"), current_qty - target), "f"),
                "position_target": format(target, "f"),
            }
        )
    if not holdings_actionable and result_action in {"REDUCE", "EXIT"} and "HARD_STOP" not in {event["event_type"] for event in events}:
        reasons.append("持仓时效不足，不发出新的精确数量建议")
        events[:] = [event for event in events if event["event_type"] in {"HARD_STOP"}]
        if not events:
            result_action = "HOLD"

    trigger_row = trigger_row or (soft_trigger if new_soft else None)
    evidence = _evidence(trigger_row)
    evidence["rule_version"] = policy.rule_version
    evidence["five_minute_status"] = five_status
    evidence["quote_status"] = quote_status
    evidence["latest_expected_closed"] = None if expected is None else expected.isoformat()
    evidence["bars_stale"] = bars_stale
    if trigger_row is None and closed:
        evidence.update({key: value for key, value in _evidence(closed[-1]).items() if key not in evidence})

    leg_exits = tuple(
        LegExit(
            leg_id=leg.leg_id,
            target_quantity=remaining[leg.leg_id],
            reason=hard_reasons.get(leg.leg_id) or (plan.reason or "hold"),
            action="EXIT" if remaining[leg.leg_id] == 0 and leg.quantity > 0 else plan.action if plan.status == "PENDING" else "HOLD",
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
        episode_consumed=episode_consumed,
        needs_review=needs_review,
        last_bar_end=last_bar_end,
        last_vwap_mode=last_vwap,
        plan=plan,
        legs=legs_state,
        rule_version=policy.rule_version,
    )
    return PositionExitResult(
        action=result_action,
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
        needs_review=needs_review,
        episode_consumed=episode_consumed,
        latest_expected_closed=expected,
        bars_stale=bars_stale,
    )
