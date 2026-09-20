# -*- coding: utf-8 -*-
"""exit_v1: medium-term CORE/ADDON protection. Quote vs active stop only; no 5m weakness."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from ...core.time import utc_now  # pragma: allowlist secret
from ..config import get_risk_policy  # pragma: allowlist secret
from ..models import PositionContext, QuoteView, StrategyProposal  # pragma: allowlist secret
from ..position_risk import compute_position_risk, position_stage, position_stop  # pragma: allowlist secret

KEY = "exit_v1"
VERSION = "1"
QUOTE_FUTURE_SKEW = timedelta(seconds=5)
EXIT_REVIEW_COOLDOWN = timedelta(minutes=30)


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _dump_dec(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


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

    def evaluate(self, context: PositionContext) -> list[StrategyProposal]:
        position = context.position
        quote = context.quote
        policy = context.policy or get_risk_policy()
        now = context.now or utc_now()
        state = context.strategy_state
        bars = list(context.daily_bars or ())
        existing = {"lots": state.get("lots") or {}}
        _risk, lot_state = compute_position_risk(position, bars, existing, policy)
        lots = position.lots or ()
        remaining = {lot.lot_id: lot.quantity for lot in lots}
        quote_status = _quote_status(quote, now)
        hit: dict[str, str] = {}
        if quote_status == "OK" and quote is not None:
            for lot in lots:
                if lot.quantity <= 0:
                    continue
                stop = _dec(lot_state[lot.lot_id].get("active_stop"))
                effective = _dt(lot_state[lot.lot_id].get("stop_effective_at"))
                if stop is None:
                    continue
                if effective is not None and quote.quote_as_of is not None and effective > quote.quote_as_of:
                    continue
                if quote.price <= stop:
                    remaining[lot.lot_id] = Decimal("0")
                    hit[lot.lot_id] = "active_stop"
        current_qty = sum((lot.quantity for lot in lots), start=Decimal("0"))
        target = sum(remaining.values(), start=Decimal("0"))
        action = _action_for(target, current_qty)
        episode = int(state.get("stop_episode") or 0)
        active = bool(state.get("stop_episode_active"))
        proposals: list[StrategyProposal] = []
        if action is None:
            state["stop_episode_active"] = False
        else:
            if not active:
                episode += 1
            proposal_key = f"exit_v1:{position.position_id}:{episode}:{action}:{format(target, 'f')}"
            resolved = set(state.get("resolved_proposal_keys") or [])
            last_review = _dt(state.get("exit_review_at"))
            cooling = (
                state.get("exit_review_key") == proposal_key
                and last_review is not None
                and now - last_review < EXIT_REVIEW_COOLDOWN
            )
            if proposal_key not in resolved and not cooling:
                evidence = {
                    "rule_version": policy.rule_version,
                    "quote_status": quote_status,
                    "profit_stage": position_stage(lot_state),
                    "active_stop": _dump_dec(position_stop(lot_state)),
                    "hit_lots": list(hit),
                    "current_quantity": format(current_qty, "f"),
                    "suggested_target_quantity": format(target, "f"),
                }
                if quote is not None:
                    evidence["price"] = format(quote.price, "f")
                reason = "报价触及保护价" if hit else "持仓保护触发"
                if len(hit) == 1:
                    lot_id = next(iter(hit))
                    role = lot_state[lot_id].get("role")
                    if role == "ADDON" and action == "REDUCE":
                        reason = "ADDON 触及独立保护价"
                proposals.append(
                    StrategyProposal(
                        market=position.market,
                        account_id=position.account_id,
                        position_id=position.position_id,
                        symbol=position.symbol,
                        strategy_key=KEY,
                        strategy_version=VERSION,
                        action=action,  # type: ignore[arg-type]
                        suggested_quantity=current_qty - target if action == "REDUCE" else current_qty,
                        suggested_target_quantity=target,
                        reason=reason,
                        evidence=evidence,
                        evaluated_at=now,
                        proposal_key=proposal_key,
                    )
                )
                state["last_proposal_key"] = proposal_key
            state["stop_episode_active"] = True
            state["stop_episode"] = episode
        highs = [_dec(item.get("high_watermark")) for item in lot_state.values()]
        highs = [item for item in highs if item is not None]
        state.update(
            {
                "highest_confirmed_close": _dump_dec(max(highs) if highs else None),
                "profit_stage": position_stage(lot_state),
                "active_stop": _dump_dec(position_stop(lot_state)),
                "lots": lot_state,
                "quote_status": quote_status,
            }
        )
        return proposals
