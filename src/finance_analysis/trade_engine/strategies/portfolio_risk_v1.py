# -*- coding: utf-8 -*-
"""Account-level Portfolio Risk Facts. Stateless; never notifies; never writes state."""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from ..config import RiskPolicy, get_risk_policy  # pragma: allowlist secret
from ..models import MarketPortfolioContext, PortfolioRiskFacts, PositionRisk, SymbolRiskFacts  # pragma: allowlist secret
from ..position_risk import open_position_risk  # pragma: allowlist secret

KEY = "portfolio_risk_v1"
VERSION = "1"


class PortfolioRiskV1:
    key = KEY
    version = VERSION
    market = None

    def evaluate_portfolio(
        self,
        context: MarketPortfolioContext,
        risks: Mapping[str, PositionRisk],
        *,
        policy: RiskPolicy | None = None,
    ) -> PortfolioRiskFacts:
        return compute_portfolio_risk_facts(context, risks, policy=policy or get_risk_policy())


def compute_portfolio_risk_facts(
    context: MarketPortfolioContext,
    risks: Mapping[str, PositionRisk],
    *,
    policy: RiskPolicy | None = None,
) -> PortfolioRiskFacts:
    policy = policy or get_risk_policy()
    positions: dict[str, SymbolRiskFacts] = {}
    if not context.valuation_complete or context.nav is None or context.nav <= 0:
        for position in context.positions:
            positions[position.symbol] = SymbolRiskFacts(
                weight=None,
                max_weight=policy.max_symbol_weight,
                open_risk=None,
                risk_limit=policy.risk_per_symbol,
            )
        return PortfolioRiskFacts(
            market=context.market,
            nav=None,
            cash=context.cash,
            gross_exposure=None,
            max_gross_exposure=policy.max_gross_exposure,
            total_open_risk=None,
            total_open_risk_limit=policy.total_open_risk,
            valuation_complete=False,
            incomplete_symbols=context.incomplete_symbols,
            positions=positions,
        )

    nav = context.nav
    risks_by_id: dict[str, Decimal] = {}
    for position in context.positions:
        price = context.valuation_prices.get(position.position_id)
        risk = risks.get(position.position_id)
        if price is None or risk is None:
            continue
        risks_by_id[position.position_id] = open_position_risk(risk, price)

    total_value = sum(context.market_values.values(), start=Decimal("0"))
    exposure = total_value / nav
    total_risk = None
    if len(risks_by_id) == len(context.positions):
        total_risk = sum(risks_by_id.values(), start=Decimal("0")) / nav

    for position in context.positions:
        value = context.market_values.get(position.position_id)
        weight = None if value is None else value / nav
        risk = risks_by_id.get(position.position_id)
        open_risk = None if risk is None else risk / nav
        positions[position.symbol] = SymbolRiskFacts(
            weight=weight,
            max_weight=policy.max_symbol_weight,
            open_risk=open_risk,
            risk_limit=policy.risk_per_symbol,
        )
    return PortfolioRiskFacts(
        market=context.market,
        nav=nav,
        cash=context.cash,
        gross_exposure=exposure,
        max_gross_exposure=policy.max_gross_exposure,
        total_open_risk=total_risk,
        total_open_risk_limit=policy.total_open_risk,
        valuation_complete=True,
        incomplete_symbols=context.incomplete_symbols,
        positions=positions,
    )
