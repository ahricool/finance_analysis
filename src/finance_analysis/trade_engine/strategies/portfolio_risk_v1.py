# -*- coding: utf-8 -*-
"""Account-level weight/risk warnings. Does not allocate sells or set target quantity."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Sequence

from finance_analysis.portfolio.models import ResolvedPosition  # pragma: allowlist secret
from finance_analysis.trade_engine.config import RiskPolicy, get_risk_policy  # pragma: allowlist secret
from finance_analysis.trade_engine.models import MarketContext, QuoteView, TradeSignal  # pragma: allowlist secret

KEY = "portfolio_risk_v1"
VERSION = "1"


def _dec(value) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _leg_risk(quantity: Decimal, price: Decimal, stop: Decimal | None) -> Decimal | None:
    if stop is None:
        return None
    gap = price - stop
    if gap <= 0:
        return Decimal("0")
    return quantity * gap


class PortfolioRiskV1:
    key = KEY
    version = VERSION
    market = None

    def evaluate(
        self,
        positions: Sequence[ResolvedPosition],
        quotes: dict[str, QuoteView],
        market_context: MarketContext,
        states: dict[str, dict[str, Any]],
        *,
        cash: Decimal,
        policy: RiskPolicy | None = None,
    ) -> list[TradeSignal]:
        policy = policy or get_risk_policy()
        eligible = [item for item in positions if item.trade_engine_eligible]
        values: dict[str, Decimal] = {}
        risks: dict[str, Decimal | None] = {}
        total_value = Decimal("0")
        for position in eligible:
            quote = quotes.get(position.symbol)
            if quote is None or not quote.valid or quote.stale or quote.quote_as_of is None:
                values[position.position_id] = Decimal("0")
                risks[position.position_id] = None
                continue
            value = position.quantity * quote.price
            values[position.position_id] = value
            total_value += value
            stop = None
            lot_states = (states.get(position.position_id) or {}).get("lots") or {}
            stops = [_dec(item.get("active_stop")) for item in lot_states.values()]
            stops = [item for item in stops if item is not None]
            if stops:
                stop = max(stops)
            risks[position.position_id] = _leg_risk(position.quantity, quote.price, stop)
        nav = cash + total_value
        signals: list[TradeSignal] = []
        if nav <= 0:
            return signals

        def emit(kind: str, current: Decimal, limit: Decimal, reason: str, position: ResolvedPosition | None = None):
            key = f"{KEY}:{market_context.market}:{kind}:{None if position is None else position.position_id}"
            signals.append(
                TradeSignal(
                    strategy_key=KEY,
                    strategy_version=VERSION,
                    market=market_context.market,
                    account_id=None if position is None else position.account_id,
                    position_id=None if position is None else position.position_id,
                    symbol=None if position is None else position.symbol,
                    action="WARNING",
                    suggested_target_quantity=None,
                    reason=reason,
                    evidence={
                        "current": format(current, "f"),
                        "limit": format(limit, "f"),
                        "nav": format(nav, "f"),
                    },
                    evaluated_at=market_context.as_of,
                    signal_key=key,
                )
            )

        for position in eligible:
            weight = values.get(position.position_id, Decimal("0")) / nav
            if weight > policy.max_symbol_weight:
                emit(
                    "max_symbol_weight",
                    weight,
                    policy.max_symbol_weight,
                    f"{position.symbol} 仓位超限",
                    position,
                )
            risk = risks.get(position.position_id)
            if risk is not None and risk / nav > policy.risk_per_symbol:
                emit(
                    "risk_per_symbol",
                    risk / nav,
                    policy.risk_per_symbol,
                    f"{position.symbol} 计划风险超限",
                    position,
                )
        exposure = total_value / nav
        if exposure > policy.max_gross_exposure:
            emit("max_gross_exposure", exposure, policy.max_gross_exposure, "总仓位超限")
        known_risks = [item for item in risks.values() if item is not None]
        if known_risks and len(known_risks) == len(eligible):
            total_risk = sum(known_risks, start=Decimal("0")) / nav
            if total_risk > policy.total_open_risk:
                emit("total_open_risk", total_risk, policy.total_open_risk, "组合计划风险超限")
        return signals
