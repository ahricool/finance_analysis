# -*- coding: utf-8 -*-
"""Account-level constraints after position exits. Missing FX or valuation is uncovered, not zero."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Mapping, Sequence

from .config import RiskPolicy
from .exits import PositionExitResult, PositionInput, QuoteView, _make_plan


@dataclass(frozen=True, slots=True)
class AccountView:
    account_id: str
    base_currency: str
    net_asset: Decimal | None
    nav_evaluable: bool


@dataclass(frozen=True, slots=True)
class PositionAccountRisk:
    account_id: str
    position_id: str
    symbol: str
    quantity: Decimal
    target_quantity: Decimal
    reduce_quantity: Decimal
    market_value: Decimal | None
    current_risk: Decimal | None
    post_plan_risk: Decimal | None
    current_weight: Decimal | None
    post_plan_weight: Decimal | None
    uncovered_risk: bool
    account_complete: bool
    triggered: bool
    execution: str
    unmet: tuple[str, ...]
    leg_targets: dict[str, Decimal]


def _leg_risk(quantity: Decimal, price: Decimal, stop: Decimal | None) -> Decimal | None:
    if stop is None:
        return None
    gap = price - stop
    if gap <= 0:
        return Decimal("0")
    return quantity * gap


def _cut_to_target(
    position: PositionInput,
    remaining: dict[str, Decimal],
    allowed: Decimal,
) -> dict[str, Decimal]:
    current = dict(remaining)
    total = sum(current.values(), start=Decimal("0"))
    if total <= allowed:
        return current
    need = total - allowed
    order = sorted(
        position.legs,
        key=lambda leg: (0 if leg.role == "ADDON" else 1, -leg.entry_time.timestamp(), leg.leg_id),
    )
    for leg in order:
        if need <= 0:
            break
        take = min(current[leg.leg_id], need)
        current[leg.leg_id] -= take
        need -= take
    return current


def apply_account_constraints(
    *,
    account: AccountView,
    positions: Sequence[tuple[PositionInput, PositionExitResult, QuoteView | None]],
    policy: RiskPolicy,
    currencies: Mapping[str, str],
) -> dict[tuple[str, str], PositionAccountRisk]:
    def _uncovered(reason: str) -> dict[tuple[str, str], PositionAccountRisk]:
        result: dict[tuple[str, str], PositionAccountRisk] = {}
        for position, exit_result, _quote in positions:
            quantity = sum((leg.quantity for leg in position.legs), start=Decimal("0"))
            result[(position.account_id, position.position_id)] = PositionAccountRisk(
                account_id=position.account_id,
                position_id=position.position_id,
                symbol=position.symbol,
                quantity=quantity,
                target_quantity=exit_result.position_target,
                reduce_quantity=exit_result.reduce_quantity,
                market_value=None,
                current_risk=None,
                post_plan_risk=None,
                current_weight=None,
                post_plan_weight=None,
                uncovered_risk=True,
                account_complete=False,
                triggered=False,
                execution="UNKNOWN",
                unmet=(reason,),
                leg_targets={item.leg_id: item.target_quantity for item in exit_result.leg_exits},
            )
        return result

    if not account.nav_evaluable or account.net_asset is None or account.net_asset <= 0:
        return _uncovered("account_nav_unavailable")
    mixed = {currencies.get(position.symbol, account.base_currency) for position, _, _ in positions}
    mixed.add(account.base_currency)
    if len({item for item in mixed if item}) > 1:
        return _uncovered("fx_unavailable")

    net = account.net_asset
    grouped: dict[str, list[tuple[PositionInput, PositionExitResult, QuoteView | None]]] = {}
    for item in positions:
        grouped.setdefault(item[0].symbol, []).append(item)

    per_symbol_allowed: dict[str, Decimal] = {}
    per_symbol_unmet: dict[str, list[str]] = {}
    per_symbol_meta: dict[str, dict] = {}
    for symbol, items in grouped.items():
        quantity = Decimal("0")
        value = Decimal("0")
        planned = Decimal("0")
        uncovered = False
        triggered = False
        missing_quote = False
        remaining = Decimal("0")
        price = None
        for position, exit_result, quote in items:
            remaining += exit_result.position_target
            for leg, leg_exit in zip(position.legs, exit_result.leg_exits):
                quantity += leg.quantity
                if quote is None or quote.quote_as_of is None or not quote.valid or quote.stale:
                    missing_quote = True
                    uncovered = True
                    continue
                price = quote.price
                value += leg.quantity * quote.price
                stop = leg_exit.active_stop
                risk = _leg_risk(leg.quantity, quote.price, stop)
                if risk is None:
                    uncovered = True
                    continue
                if quote.price <= stop:
                    triggered = True
                    continue
                planned += risk
        unmet: list[str] = []
        allowed = remaining
        if missing_quote:
            unmet.append("quote_unavailable")
        elif price is not None and price > 0:
            weight = value / net
            if weight > policy.max_symbol_weight:
                allowed = min(allowed, policy.max_symbol_weight * net / price)
                unmet.append("max_symbol_weight")
            if not uncovered and planned > 0:
                risk_ratio = planned / net
                if risk_ratio > policy.risk_per_symbol:
                    per_share = planned / quantity if quantity else None
                    if per_share:
                        allowed = min(allowed, (policy.risk_per_symbol * net) / per_share)
                    unmet.append("risk_per_symbol")
        per_symbol_allowed[symbol] = max(Decimal("0"), allowed)
        per_symbol_unmet[symbol] = unmet
        per_symbol_meta[symbol] = {
            "value": None if missing_quote else value,
            "planned": None if uncovered else planned,
            "uncovered": uncovered or missing_quote,
            "triggered": triggered,
            "quantity": quantity,
            "price": price,
            "missing_quote": missing_quote,
        }

    gross = sum((meta["value"] or Decimal("0") for meta in per_symbol_meta.values()), start=Decimal("0"))
    open_risk = sum((meta["planned"] or Decimal("0") for meta in per_symbol_meta.values()), start=Decimal("0"))
    complete = not any(meta["uncovered"] for meta in per_symbol_meta.values())
    extra_unmet: list[str] = []
    if complete and gross > policy.max_gross_exposure * net:
        extra_unmet.append("max_gross_exposure")
        scale = (policy.max_gross_exposure * net) / gross if gross else Decimal("0")
        for symbol, allowed in list(per_symbol_allowed.items()):
            price = per_symbol_meta[symbol]["price"]
            value = per_symbol_meta[symbol]["value"]
            if price and value:
                per_symbol_allowed[symbol] = min(allowed, (value * scale) / price)
    if complete and open_risk > policy.total_open_risk * net:
        extra_unmet.append("total_open_risk")
        scale = (policy.total_open_risk * net) / open_risk if open_risk else Decimal("0")
        for symbol, allowed in list(per_symbol_allowed.items()):
            per_symbol_allowed[symbol] = min(allowed, allowed * scale)

    result: dict[tuple[str, str], PositionAccountRisk] = {}
    for symbol, items in grouped.items():
        budget = per_symbol_allowed[symbol]
        ordered = sorted(items, key=lambda item: item[0].position_id)
        for position, exit_result, quote in ordered:
            remaining = {item.leg_id: item.target_quantity for item in exit_result.leg_exits}
            total = sum(remaining.values(), start=Decimal("0"))
            take = min(total, budget)
            budget -= take
            remaining = _cut_to_target(position, remaining, take)
            target = sum(remaining.values(), start=Decimal("0"))
            quantity = sum((leg.quantity for leg in position.legs), start=Decimal("0"))
            price = quote.price if quote is not None and quote.valid else None
            value = None if price is None else quantity * price
            post_value = None if price is None else target * price
            current_risk = Decimal("0")
            post_risk = Decimal("0")
            risk_unknown = False
            for leg, leg_exit in zip(position.legs, exit_result.leg_exits):
                if price is None:
                    risk_unknown = True
                    break
                current = _leg_risk(leg.quantity, price, leg_exit.active_stop)
                planned = _leg_risk(remaining[leg.leg_id], price, leg_exit.active_stop)
                if current is None or planned is None:
                    risk_unknown = True
                    break
                current_risk += current
                post_risk += planned
            execution = "UNKNOWN"
            available = [
                leg.available_quantity
                for leg in position.legs
                if leg.available_quantity is not None
            ]
            reduce_qty = max(Decimal("0"), quantity - target)
            if available and reduce_qty > 0:
                free = sum(available, start=Decimal("0"))
                if free <= 0:
                    execution = "BLOCKED"
                elif free < reduce_qty:
                    execution = "PARTIALLY_AVAILABLE"
                else:
                    execution = "AVAILABLE"
            unmet = tuple(per_symbol_unmet[symbol] + extra_unmet)
            result[(position.account_id, position.position_id)] = PositionAccountRisk(
                account_id=position.account_id,
                position_id=position.position_id,
                symbol=symbol,
                quantity=quantity,
                target_quantity=target,
                reduce_quantity=reduce_qty,
                market_value=value,
                current_risk=None if risk_unknown else current_risk,
                post_plan_risk=None if risk_unknown else post_risk,
                current_weight=None if value is None else value / net,
                post_plan_weight=None if post_value is None else post_value / net,
                uncovered_risk=per_symbol_meta[symbol]["uncovered"],
                account_complete=complete,
                triggered=per_symbol_meta[symbol]["triggered"],
                execution=execution,
                unmet=unmet,
                leg_targets=remaining,
            )
    return result


def merge_account_targets(
    position: PositionInput,
    exit_result: PositionExitResult,
    risk: PositionAccountRisk,
) -> PositionExitResult:
    if risk.target_quantity >= exit_result.position_target and not risk.unmet:
        return replace(
            exit_result,
            evidence={
                **exit_result.evidence,
                "current_risk": None if risk.current_risk is None else format(risk.current_risk, "f"),
                "post_plan_risk": None if risk.post_plan_risk is None else format(risk.post_plan_risk, "f"),
                "account_complete": risk.account_complete,
                "execution": risk.execution,
            },
        )
    if risk.target_quantity >= exit_result.position_target:
        plan = exit_result.plan.model_copy(update={"execution": risk.execution})
        return replace(
            exit_result,
            plan=plan,
            state=replace(exit_result.state, plan=plan),
            evidence={
                **exit_result.evidence,
                "current_risk": None if risk.current_risk is None else format(risk.current_risk, "f"),
                "post_plan_risk": None if risk.post_plan_risk is None else format(risk.post_plan_risk, "f"),
                "account_unmet": list(risk.unmet),
                "account_complete": risk.account_complete,
                "execution": risk.execution,
            },
        )
    remaining = dict(risk.leg_targets)
    current_qty = risk.quantity
    events = list(exit_result.events)
    plan = exit_result.plan
    if plan.status != "PENDING" or Decimal(plan.position_target or current_qty) > risk.target_quantity:
        plan = _make_plan(
            previous=plan,
            remaining=remaining,
            current_qty=current_qty,
            episode_id=plan.episode_id or exit_result.state.episode_id,
            bound_leg_ids=[leg.leg_id for leg in position.legs],
            reason=";".join(risk.unmet) or "account_constraint",
            created_bar_end=plan.created_bar_end or exit_result.evaluated_bar_end,
            hard_locked=plan.hard_locked,
            trigger_event="ACCOUNT_CONSTRAINT",
            execution=risk.execution,
        )
        events.append(
            {
                "event_type": "ACCOUNT_CONSTRAINT",
                "action": plan.action,
                "episode_id": plan.episode_id,
                "plan_revision": plan.revision,
            }
        )
    else:
        plan = plan.model_copy(
            update={
                "leg_targets": {leg_id: format(qty, "f") for leg_id, qty in remaining.items()},
                "position_target": format(risk.target_quantity, "f"),
                "current_quantity": format(current_qty, "f"),
                "reduce_quantity": format(max(Decimal("0"), current_qty - risk.target_quantity), "f"),
                "execution": risk.execution,
            }
        )
    leg_exits = tuple(
        replace(item, target_quantity=remaining.get(item.leg_id, item.target_quantity), action=plan.action)
        for item in exit_result.leg_exits
    )
    state = replace(exit_result.state, plan=plan)
    evidence = {
        **exit_result.evidence,
        "current_risk": None if risk.current_risk is None else format(risk.current_risk, "f"),
        "post_plan_risk": None if risk.post_plan_risk is None else format(risk.post_plan_risk, "f"),
        "account_unmet": list(risk.unmet),
        "account_complete": risk.account_complete,
        "execution": risk.execution,
        "advice_not_fill": True,
    }
    return replace(
        exit_result,
        action=plan.action,
        plan=plan,
        state=state,
        leg_exits=leg_exits,
        position_target=risk.target_quantity,
        reduce_quantity=risk.reduce_quantity,
        events=tuple(events),
        evidence=evidence,
        reasons=tuple(list(exit_result.reasons) + [f"account:{item}" for item in risk.unmet]),
    )
