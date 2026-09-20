# -*- coding: utf-8 -*-
"""add_v1: one medium-term ADD after a complete daily setup. No averaging down."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Sequence

from ...core.time import utc_now  # pragma: allowlist secret
from ..config import RiskPolicy, get_risk_policy  # pragma: allowlist secret
from ..daily import atr, extension_atr, last_complete_date, legalize_quantity, ma_slope, sma_series, volume_median
from ..models import DailyBar, PositionContext, StrategyProposal  # pragma: allowlist secret

KEY = "add_v1"
VERSION = "1"
BREAKOUT = "BREAKOUT_CONTINUATION"
PULLBACK = "PULLBACK_REENTRY"


def _dump(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _ma_at(series: Sequence[Decimal | None], index: int) -> Decimal | None:
    if index < 0 or index >= len(series):
        return None
    return series[index]


class AddV1:
    key = KEY
    version = VERSION
    market = None

    def evaluate(self, context: PositionContext) -> list[StrategyProposal]:
        position = context.position
        policy = context.policy or get_risk_policy()
        now = context.now or utc_now()
        state = context.strategy_state
        bars = list(context.daily_bars or ())
        if position.source != "DB":
            return []
        if position.quantity <= 0 or position.asset_type.upper() not in {"STOCK", "ETF"}:
            return []
        if position.had_addon:
            return []
        complete = last_complete_date(bars)
        if complete is None:
            return []
        if state.get("last_setup_date") == complete.isoformat():
            return []
        setup = evaluate_add_setup(context, bars, policy)
        state["last_setup_date"] = complete.isoformat()
        if setup is None:
            return []
        proposal_key = (
            f"add_v1:{position.position_id}:{setup['setup']}:{complete.isoformat()}:"
            f"{format(setup['suggested_target_quantity'], 'f')}"
        )
        resolved = set(state.get("resolved_proposal_keys") or [])
        if proposal_key in resolved or state.get("last_proposal_key") == proposal_key:
            return []
        state["last_proposal_key"] = proposal_key
        evidence = {key: _dump(value) if isinstance(value, Decimal) else value for key, value in setup.items()}
        return [
            StrategyProposal(
                market=position.market,
                account_id=position.account_id,
                position_id=position.position_id,
                symbol=position.symbol,
                strategy_key=KEY,
                strategy_version=VERSION,
                action="ADD",
                suggested_quantity=setup["suggested_add_quantity"],
                suggested_target_quantity=setup["suggested_target_quantity"],
                reason=setup["reason"],
                evidence=evidence,
                evaluated_at=now,
                proposal_key=proposal_key,
            )
        ]


def evaluate_add_setup(
    context: PositionContext,
    bars: Sequence[DailyBar],
    policy: RiskPolicy,
) -> dict[str, Any] | None:
    position = context.position
    last = bars[-1]
    closes = [bar.close for bar in bars]
    ma_fast = sma_series(closes, policy.add_ma_fast)
    ma_slow = sma_series(closes, policy.add_ma_slow)
    last_ma10 = ma_fast[-1]
    last_ma20 = ma_slow[-1]
    atr_value = atr(bars, policy.atr_period)
    slope = ma_slope(ma_fast, 5)
    if last_ma10 is None or last_ma20 is None or atr_value is None or atr_value <= 0 or slope is None:
        return None
    price = last.close
    if position.average_cost <= 0 or price <= position.average_cost:
        return None
    pnl = price / position.average_cost - Decimal("1")
    if pnl < policy.min_profit_to_add:
        return None
    if last.close <= last_ma10 or last_ma10 <= last_ma20 or slope <= 0:
        return None
    stage = context.risk.profit_stage or "UNKNOWN"
    if stage == "C":
        return None
    stop = context.risk.active_stop
    if stop is None:
        return None
    stop_distance = (price - stop) / atr_value
    if stop_distance < policy.min_stop_distance_atr:
        return None
    extension = extension_atr(last.close, last_ma10, atr_value)
    if extension is None or extension > policy.max_extension_atr:
        return None
    if context.cash <= 0 or context.market_nav <= 0:
        return None
    current_value = position.quantity * price
    max_position_value = context.market_nav * policy.max_symbol_weight
    remaining_capacity = max_position_value - current_value
    max_add_value = max_position_value * policy.max_add_value_fraction
    allowed_by_position = min(remaining_capacity, max_add_value)
    if allowed_by_position <= 0:
        return None
    existing_risk = Decimal("0")
    for lot in context.risk.lots:
        if lot.quantity <= 0 or lot.active_stop is None:
            continue
        gap = price - lot.active_stop
        if gap > 0:
            existing_risk += lot.quantity * gap
    risk_budget = context.market_nav * policy.risk_per_symbol
    remaining_risk = risk_budget - existing_risk
    if remaining_risk <= 0:
        return None
    vol_med = volume_median(bars[:-1], 20) if len(bars) > 20 else volume_median(bars[:-1], max(5, len(bars) - 1))
    pullback = _pullback(bars, ma_fast, ma_slow, atr_value, vol_med, position.average_cost, policy)
    breakout = _breakout(bars, ma_fast, ma_slow, atr_value, vol_med, policy)
    chosen = pullback or breakout
    if chosen is None:
        return None
    entry = last.close
    structure_stop = chosen["suggested_stop"]
    risk_per_share = entry - structure_stop
    if risk_per_share <= 0:
        return None
    if risk_per_share > policy.max_stop_atr * atr_value:
        return None
    qty_by_position = allowed_by_position / entry
    qty_by_risk = remaining_risk / risk_per_share
    qty_by_cash = context.cash / entry
    add_qty = legalize_quantity(min(qty_by_position, qty_by_risk, qty_by_cash), position.market)
    if add_qty <= 0:
        return None
    target = position.quantity + add_qty
    weight = current_value / context.market_nav if context.market_nav > 0 else Decimal("0")
    return {
        "setup": chosen["setup"],
        "reason": chosen["reason"],
        "current_quantity": position.quantity,
        "current_price": price,
        "average_cost": position.average_cost,
        "unrealized_pnl": pnl,
        "MA10": last_ma10,
        "MA20": last_ma20,
        "MA10_slope": slope,
        "ATR14": atr_value,
        "extension_atr": extension,
        "active_stop": stop,
        "profit_stage": stage,
        "current_weight": weight,
        "target_weight": policy.max_symbol_weight,
        "risk_before": existing_risk,
        "risk_after": existing_risk + add_qty * risk_per_share,
        "risk_budget": risk_budget,
        "suggested_entry_price": entry,
        "suggested_stop": structure_stop,
        "suggested_add_quantity": add_qty,
        "suggested_target_quantity": target,
        "qty_by_position": legalize_quantity(qty_by_position, position.market),
        "qty_by_risk": legalize_quantity(qty_by_risk, position.market),
        "qty_by_cash": legalize_quantity(qty_by_cash, position.market),
        "daily_bar_date": last.trade_date.isoformat(),
        "stop_distance_atr": stop_distance,
    }


def _closes_hold_ma(window: Sequence[DailyBar], ma_series: Sequence[Decimal | None], offset: int) -> bool:
    for index, bar in enumerate(window):
        ma = _ma_at(ma_series, offset + index)
        if ma is None or bar.close < ma:
            return False
    return True


def _breakout(
    bars: Sequence[DailyBar],
    ma_fast: Sequence[Decimal | None],
    ma_slow: Sequence[Decimal | None],
    atr_value: Decimal,
    vol_med: Decimal | None,
    policy: RiskPolicy,
) -> dict[str, Any] | None:
    last = bars[-1]
    prior = list(bars[:-1])
    if len(prior) < policy.consolidation_max_days:
        return None
    if vol_med is None or last.volume < int(policy.min_breakout_volume_ratio * vol_med):
        return None
    lookback_highs = prior[-5:] if len(prior) >= 5 else prior
    if last.close <= max(bar.high for bar in lookback_highs):
        return None
    for length in range(policy.consolidation_max_days, policy.consolidation_min_days - 1, -1):
        window = prior[-length:]
        start = len(prior) - length
        if not _closes_hold_ma(window, ma_fast, start):
            continue
        if not _closes_hold_ma(window, ma_slow, start):
            continue
        platform_range = max(bar.high for bar in window) - min(bar.low for bar in window)
        if platform_range > Decimal("2.5") * atr_value:
            continue
        return {
            "setup": BREAKOUT,
            "reason": "整理后日线突破确认",
            "suggested_stop": min(bar.low for bar in window),
        }
    return None


def _pullback(
    bars: Sequence[DailyBar],
    ma_fast: Sequence[Decimal | None],
    ma_slow: Sequence[Decimal | None],
    atr_value: Decimal,
    vol_med: Decimal | None,
    average_cost: Decimal,
    policy: RiskPolicy,
) -> dict[str, Any] | None:
    last = bars[-1]
    prior = list(bars[:-1])
    if len(prior) < policy.pullback_max_days:
        return None
    recent_high = max(bar.high for bar in prior)
    if recent_high < average_cost * (Decimal("1") + policy.pullback_high_min):
        return None
    previous = prior[-1]
    last_ma10 = ma_fast[-1]
    if last_ma10 is None or last.close <= previous.high or last.close <= last_ma10:
        return None
    for length in range(policy.pullback_min_days, policy.pullback_max_days + 1):
        window = prior[-length:]
        start = len(prior) - length
        if not _closes_hold_ma(window, ma_slow, start):
            continue
        lows = [bar.low for bar in window]
        depth = recent_high - min(lows)
        pct_cap = recent_high * Decimal("0.08")
        if depth > policy.max_extension_atr * atr_value and depth > pct_cap:
            continue
        if vol_med is not None and any(bar.volume >= int(vol_med) for bar in window):
            continue
        pierced = False
        for index, bar in enumerate(window):
            ma20 = _ma_at(ma_slow, start + index)
            if ma20 is None:
                pierced = True
                break
            if bar.low < ma20 - Decimal("0.5") * atr_value:
                pierced = True
                break
        if pierced:
            continue
        return {
            "setup": PULLBACK,
            "reason": "盈利后健康回踩再转强",
            "suggested_stop": min(lows),
        }
    return None
