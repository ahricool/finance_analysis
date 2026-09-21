# -*- coding: utf-8 -*-
"""exit_v1: stateless medium-term CORE/ADDON protection from quote vs recomputed stops."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from ...core.time import utc_now  # pragma: allowlist secret
from ..config import get_risk_policy  # pragma: allowlist secret
from ..models import PositionContext, QuoteView, StrategySignal  # pragma: allowlist secret

KEY = "exit_v1"
VERSION = "1"
QUOTE_FUTURE_SKEW = timedelta(seconds=5)


def _dump_dec(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _quote_status(quote: QuoteView | None, now) -> str:
    if quote is None or quote.price is None:
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


def _action_for(target: Decimal, current: Decimal) -> str | None:
    if target <= 0 and current > 0:
        return "EXIT"
    if target < current:
        return "REDUCE"
    return None


class ExitV1:
    key = KEY
    version = VERSION
    market = None

    def evaluate(self, context: PositionContext) -> list[StrategySignal]:
        position = context.position
        quote = context.quote
        policy = context.policy or get_risk_policy()
        now = context.now or utc_now()
        quote_status = _quote_status(quote, now)
        remaining = {lot.lot_id: lot.quantity for lot in position.lots}
        hit: dict[str, str] = {}
        if quote_status == "OK" and quote is not None and quote.price is not None:
            for lot in context.risk.lots:
                if lot.quantity <= 0 or lot.active_stop is None:
                    continue
                if (
                    lot.stop_effective_at is not None
                    and quote.quote_as_of is not None
                    and lot.stop_effective_at > quote.quote_as_of
                ):
                    continue
                if quote.price <= lot.active_stop:
                    remaining[lot.lot_id] = Decimal("0")
                    hit[lot.lot_id] = "active_stop"
        current_qty = sum((lot.quantity for lot in position.lots), start=Decimal("0"))
        target = sum(remaining.values(), start=Decimal("0"))
        action = _action_for(target, current_qty)
        if action is None:
            return []
        reason = "报价触及保护价" if hit else "持仓保护触发"
        if len(hit) == 1:
            lot_id = next(iter(hit))
            role = next((item.role for item in context.risk.lots if item.lot_id == lot_id), None)
            if role == "ADDON" and action == "REDUCE":
                reason = "ADDON 触及独立保护价"
        evidence = {
            "rule_version": policy.rule_version,
            "quote_status": quote_status,
            "profit_stage": context.risk.profit_stage,
            "active_stop": _dump_dec(context.risk.active_stop),
            "hit_lots": list(hit),
            "current_quantity": format(current_qty, "f"),
            "suggested_target_quantity": format(target, "f"),
        }
        if quote is not None and quote.price is not None:
            evidence["price"] = format(quote.price, "f")
        return [
            StrategySignal(
                strategy_key=KEY,
                strategy_version=VERSION,
                market=position.market,
                account_id=position.account_id,
                position_id=position.position_id,
                symbol=position.symbol,
                action=action,  # type: ignore[arg-type]
                suggested_quantity=current_qty - target if action == "REDUCE" else current_qty,
                suggested_target_quantity=target,
                reason=reason,
                evidence=evidence,
                evaluated_at=now,
            )
        ]
