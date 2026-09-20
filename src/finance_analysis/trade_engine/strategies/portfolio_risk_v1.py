# -*- coding: utf-8 -*-
"""Account-level Portfolio Warning. Not a Strategy Proposal. Never sent to LLM."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping
from uuid import uuid4

from ...core.time import utc_now  # pragma: allowlist secret
from ...portfolio.models import ResolvedPosition  # pragma: allowlist secret
from ..config import RiskPolicy, get_risk_policy  # pragma: allowlist secret
from ..models import MarketPortfolioContext, PortfolioWarning, PositionRisk  # pragma: allowlist secret
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
        now=None,
        policy: RiskPolicy | None = None,
        strategy_state: dict[str, Any] | None = None,
    ) -> list[PortfolioWarning]:
        policy = policy or get_risk_policy()
        now = now or utc_now()
        state = strategy_state if strategy_state is not None else {}
        state["valuation_complete"] = context.valuation_complete
        state["cash"] = format(context.cash, "f")
        if context.incomplete_symbols:
            state["incomplete_symbols"] = list(context.incomplete_symbols)
        else:
            state.pop("incomplete_symbols", None)
        if not context.valuation_complete or context.nav is None or context.nav <= 0:
            state["nav"] = None
            state["gross_exposure"] = None
            return []

        nav = context.nav
        values = context.market_values
        positions = context.positions
        risks_by_id: dict[str, Decimal] = {}
        for position in positions:
            price = context.valuation_prices.get(position.position_id)
            risk = risks.get(position.position_id)
            if price is None or risk is None:
                continue
            risks_by_id[position.position_id] = open_position_risk(risk, price)

        total_value = sum(values.values(), start=Decimal("0"))
        exposure = total_value / nav
        pending: list[tuple[str, Decimal, Decimal, str, ResolvedPosition | None]] = []

        def consider(kind: str, current: Decimal, limit: Decimal, reason: str, position: ResolvedPosition | None = None):
            pending.append((kind, current, limit, reason, position))

        for position in positions:
            value = values.get(position.position_id, Decimal("0"))
            weight = value / nav
            if weight > policy.max_symbol_weight:
                consider("max_symbol_weight", weight, policy.max_symbol_weight, f"{position.symbol} 仓位超限", position)
            risk = risks_by_id.get(position.position_id)
            if risk is not None and risk / nav > policy.risk_per_symbol:
                consider("risk_per_symbol", risk / nav, policy.risk_per_symbol, f"{position.symbol} 计划风险超限", position)
        if exposure > policy.max_gross_exposure:
            consider("max_gross_exposure", exposure, policy.max_gross_exposure, "总仓位超限")
        if len(risks_by_id) == len(positions):
            total_risk = sum(risks_by_id.values(), start=Decimal("0")) / nav
            if total_risk > policy.total_open_risk:
                consider("total_open_risk", total_risk, policy.total_open_risk, "组合计划风险超限")

        episodes: dict[str, dict[str, Any]] = dict(state.get("episodes") or {})
        current_active: set[str] = set()
        warnings: list[PortfolioWarning] = []
        for kind, current, limit, reason, position in pending:
            slot = f"{kind}:{None if position is None else position.position_id}"
            current_active.add(slot)
            row = episodes.get(slot) or {}
            if row.get("active"):
                continue
            episode_id = str(row.get("next_id") or uuid4().hex)
            warning_key = f"{KEY}:{context.market}:{kind}:{None if position is None else position.position_id}:{episode_id}"
            episodes[slot] = {"active": True, "episode_id": episode_id, "next_id": uuid4().hex, "warning_key": warning_key}
            warnings.append(
                PortfolioWarning(
                    market=context.market,
                    account_id=None if position is None else position.account_id,
                    position_id=None if position is None else position.position_id,
                    symbol=None if position is None else position.symbol,
                    kind=kind,
                    reason=reason,
                    current=current,
                    limit=limit,
                    evidence={
                        "current": format(current, "f"),
                        "limit": format(limit, "f"),
                        "nav": format(nav, "f"),
                        "cash": format(context.cash, "f"),
                        "gross_exposure": format(exposure, "f"),
                        "episode_id": episode_id,
                    },
                    evaluated_at=now,
                    warning_key=warning_key,
                )
            )
        for slot, row in list(episodes.items()):
            if slot not in current_active:
                episodes[slot] = {**row, "active": False}
        state["active_keys"] = sorted(current_active)
        state["episodes"] = episodes
        state["nav"] = format(nav, "f")
        state["gross_exposure"] = format(exposure, "f")
        return warnings
