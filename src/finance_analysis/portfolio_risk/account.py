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


class _Slice:
    __slots__ = ("account_id", "position_id", "symbol", "leg", "stop", "price", "qty", "candidate")

    def __init__(
        self,
        *,
        account_id: str,
        position_id: str,
        symbol: str,
        leg: object,
        stop: Decimal | None,
        price: Decimal | None,
        qty: Decimal,
    ) -> None:
        self.account_id = account_id
        self.position_id = position_id
        self.symbol = symbol
        self.leg = leg
        self.stop = stop
        self.price = price
        self.qty = qty
        self.candidate = qty


def _slice_key(item: _Slice) -> tuple:
    return (0 if item.leg.role == "ADDON" else 1, -item.leg.entry_time.timestamp(), item.position_id, item.leg.leg_id)


def _value_of(slices: Sequence[_Slice]) -> Decimal:
    return sum((item.qty * item.price for item in slices if item.price is not None), start=Decimal("0"))


def _risk_of(slices: Sequence[_Slice]) -> Decimal | None:
    total = Decimal("0")
    for item in slices:
        if item.price is None:
            return None
        risk = _leg_risk(item.qty, item.price, item.stop)
        if risk is None:
            return None
        total += risk
    return total


def _reduce_value(slices: Sequence[_Slice], budget: Decimal) -> bool:
    value = _value_of(slices)
    if value <= budget:
        return False
    need = value - budget
    changed = False
    for item in sorted(slices, key=_slice_key):
        if need <= 0 or item.price is None or item.price <= 0 or item.qty <= 0:
            continue
        take = min(item.qty, need / item.price)
        if take > 0:
            item.qty -= take
            need -= take * item.price
            changed = True
    return changed


def _reduce_risk(slices: Sequence[_Slice], budget: Decimal) -> bool:
    risk = _risk_of(slices)
    if risk is None or risk <= budget:
        return False
    need = risk - budget
    changed = False
    for item in sorted(slices, key=_slice_key):
        if need <= 0 or item.price is None or item.stop is None:
            continue
        gap = item.price - item.stop
        if gap <= 0 or item.qty <= 0:
            continue
        take = min(item.qty, need / gap)
        if take > 0:
            item.qty -= take
            need -= take * gap
            changed = True
    return changed


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
    slices: list[_Slice] = []
    quote_ok: dict[tuple[str, str], bool] = {}
    stops: dict[tuple[str, str, str], Decimal | None] = {}
    for position, exit_result, quote in positions:
        missing = quote is None or quote.quote_as_of is None or not quote.valid or quote.stale
        quote_ok[(position.account_id, position.position_id)] = not missing
        price = None if missing or quote is None else quote.price
        by_exit = {item.leg_id: item for item in exit_result.leg_exits}
        for leg in position.legs:
            leg_exit = by_exit.get(leg.leg_id)
            stop = None if leg_exit is None else leg_exit.active_stop
            stops[(position.account_id, position.position_id, leg.leg_id)] = stop
            candidate = leg.quantity if leg_exit is None else leg_exit.target_quantity
            slices.append(
                _Slice(
                    account_id=position.account_id,
                    position_id=position.position_id,
                    symbol=position.symbol,
                    leg=leg,
                    stop=stop,
                    price=price,
                    qty=candidate,
                )
            )

    grouped_slices: dict[str, list[_Slice]] = {}
    for item in slices:
        grouped_slices.setdefault(item.symbol, []).append(item)

    per_symbol_unmet: dict[str, list[str]] = {}
    per_symbol_meta: dict[str, dict] = {}
    for symbol, items in grouped_slices.items():
        missing_quote = any(item.price is None for item in items)
        uncovered = missing_quote or any(_leg_risk(item.qty, item.price, item.stop) is None for item in items if item.price is not None)
        triggered = any(
            item.price is not None and item.stop is not None and item.price <= item.stop for item in items
        )
        unmet: list[str] = []
        if missing_quote:
            unmet.append("quote_unavailable")
        else:
            if _value_of(items) / net > policy.max_symbol_weight:
                if _reduce_value(items, policy.max_symbol_weight * net):
                    unmet.append("max_symbol_weight")
            symbol_risk = _risk_of(items)
            if symbol_risk is not None and symbol_risk / net > policy.risk_per_symbol:
                if _reduce_risk(items, policy.risk_per_symbol * net):
                    unmet.append("risk_per_symbol")
        per_symbol_unmet[symbol] = unmet
        per_symbol_meta[symbol] = {
            "uncovered": uncovered or missing_quote,
            "triggered": triggered,
            "missing_quote": missing_quote,
        }

    complete = not any(meta["uncovered"] for meta in per_symbol_meta.values())
    extra_unmet: list[str] = []
    if complete:
        if _value_of(slices) > policy.max_gross_exposure * net:
            if _reduce_value(slices, policy.max_gross_exposure * net):
                extra_unmet.append("max_gross_exposure")
        total_risk = _risk_of(slices)
        if total_risk is not None and total_risk > policy.total_open_risk * net:
            if _reduce_risk(slices, policy.total_open_risk * net):
                extra_unmet.append("total_open_risk")

    by_position: dict[tuple[str, str], list[_Slice]] = {}
    for item in slices:
        by_position.setdefault((item.account_id, item.position_id), []).append(item)

    result: dict[tuple[str, str], PositionAccountRisk] = {}
    for position, exit_result, quote in positions:
        key = (position.account_id, position.position_id)
        owned = by_position.get(key, [])
        remaining = {item.leg.leg_id: item.qty for item in owned}
        for item in exit_result.leg_exits:
            remaining.setdefault(item.leg_id, item.target_quantity)
        target = sum(remaining.values(), start=Decimal("0"))
        quantity = sum((leg.quantity for leg in position.legs), start=Decimal("0"))
        price = quote.price if quote is not None and quote.valid and not quote.stale else None
        value = None if price is None else quantity * price
        post_value = None if price is None else target * price
        current_risk = Decimal("0")
        post_risk = Decimal("0")
        risk_unknown = False
        for leg in position.legs:
            stop = stops.get((position.account_id, position.position_id, leg.leg_id))
            if price is None:
                risk_unknown = True
                break
            current = _leg_risk(leg.quantity, price, stop)
            planned = _leg_risk(remaining.get(leg.leg_id, Decimal("0")), price, stop)
            if current is None or planned is None:
                risk_unknown = True
                break
            current_risk += current
            post_risk += planned
        execution = "UNKNOWN"
        available = [leg.available_quantity for leg in position.legs if leg.available_quantity is not None]
        reduce_qty = max(Decimal("0"), quantity - target)
        if available and reduce_qty > 0:
            free = sum(available, start=Decimal("0"))
            if free <= 0:
                execution = "BLOCKED"
            elif free < reduce_qty:
                execution = "PARTIALLY_AVAILABLE"
            else:
                execution = "AVAILABLE"
        cut = any(item.qty < item.candidate for item in owned)
        unmet = tuple(per_symbol_unmet[position.symbol] + extra_unmet) if cut else ()
        result[key] = PositionAccountRisk(
            account_id=position.account_id,
            position_id=position.position_id,
            symbol=position.symbol,
            quantity=quantity,
            target_quantity=target,
            reduce_quantity=reduce_qty,
            market_value=value,
            current_risk=None if risk_unknown else current_risk,
            post_plan_risk=None if risk_unknown else post_risk,
            current_weight=None if value is None else value / net,
            post_plan_weight=None if post_value is None else post_value / net,
            uncovered_risk=per_symbol_meta[position.symbol]["uncovered"],
            account_complete=complete,
            triggered=per_symbol_meta[position.symbol]["triggered"],
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
