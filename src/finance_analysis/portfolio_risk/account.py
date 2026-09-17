# -*- coding: utf-8 -*-
"""Account-level constraints after position exits. Missing FX or valuation is uncovered, not zero."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

from finance_analysis.portfolio_risk.config import RiskPolicy  # pragma: allowlist secret
from finance_analysis.portfolio_risk.exits import PositionExitResult, PositionInput, QuoteView  # pragma: allowlist secret


@dataclass(frozen=True, slots=True)
class AccountView:
    account_id: str
    base_currency: str
    net_asset: Decimal | None
    nav_evaluable: bool


@dataclass(frozen=True, slots=True)
class SymbolRisk:
    symbol: str
    quantity: Decimal
    market_value: Decimal | None
    planned_risk: Decimal | None
    uncovered_risk: bool
    triggered: bool
    target_quantity: Decimal
    reduce_quantity: Decimal
    unmet: tuple[str, ...]


def apply_account_constraints(
    *,
    account: AccountView,
    positions: Sequence[tuple[PositionInput, PositionExitResult, QuoteView | None]],
    policy: RiskPolicy,
    currencies: Mapping[str, str],
) -> dict[str, SymbolRisk]:
    if not account.nav_evaluable or account.net_asset is None or account.net_asset <= 0:
        return {
            (position.symbol): SymbolRisk(
                symbol=position.symbol,
                quantity=sum((leg.quantity for leg in position.legs), start=Decimal("0")),
                market_value=None,
                planned_risk=None,
                uncovered_risk=True,
                triggered=False,
                target_quantity=result.position_target,
                reduce_quantity=result.reduce_quantity,
                unmet=("account_nav_unavailable",),
            )
            for position, result, _quote in positions
        }
    mixed = {currencies.get(position.symbol, account.base_currency) for position, _, _ in positions}
    mixed.add(account.base_currency)
    if len({item for item in mixed if item}) > 1:
        return {
            position.symbol: SymbolRisk(
                symbol=position.symbol,
                quantity=sum((leg.quantity for leg in position.legs), start=Decimal("0")),
                market_value=None,
                planned_risk=None,
                uncovered_risk=True,
                triggered=False,
                target_quantity=result.position_target,
                reduce_quantity=result.reduce_quantity,
                unmet=("fx_unavailable",),
            )
            for position, result, _quote in positions
        }

    grouped: dict[str, list[tuple[PositionInput, PositionExitResult, QuoteView | None]]] = {}
    for item in positions:
        grouped.setdefault(item[0].symbol, []).append(item)

    net = account.net_asset
    result: dict[str, SymbolRisk] = {}
    for symbol, items in grouped.items():
        quantity = Decimal("0")
        target = Decimal("0")
        value = Decimal("0")
        planned = Decimal("0")
        uncovered = False
        triggered = False
        missing_quote = False
        for position, exit_result, quote in items:
            for leg, leg_exit in zip(position.legs, exit_result.leg_exits):
                quantity += leg.quantity
                target += leg_exit.target_quantity
                if quote is None or not quote.valid:
                    missing_quote = True
                    uncovered = True
                    continue
                value += leg.quantity * quote.price
                stop = leg_exit.active_stop
                if stop is None:
                    uncovered = True
                    continue
                if quote.price < stop:
                    triggered = True
                    continue
                planned += leg.quantity * (quote.price - stop)
        unmet: list[str] = []
        if missing_quote:
            unmet.append("quote_unavailable")
        reduce_qty = max(Decimal("0"), quantity - target)
        if not missing_quote and net > 0:
            weight = value / net
            risk_ratio = planned / net if not uncovered else None
            if weight > policy.max_symbol_weight:
                allowed = policy.max_symbol_weight * net / (items[0][2].price if items[0][2] and items[0][2].valid else Decimal("1"))
                if target > allowed:
                    target = max(Decimal("0"), allowed)
                    unmet.append("max_symbol_weight")
            if risk_ratio is not None and risk_ratio > policy.risk_per_symbol:
                unmet.append("risk_per_symbol")
        result[symbol] = SymbolRisk(
            symbol=symbol,
            quantity=quantity,
            market_value=None if missing_quote else value,
            planned_risk=None if uncovered else planned,
            uncovered_risk=uncovered,
            triggered=triggered,
            target_quantity=target,
            reduce_quantity=max(Decimal("0"), quantity - target),
            unmet=tuple(unmet),
        )
    return result
