"""Point-in-time theoretical strategy state transitions."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from finance_analysis.trend_following.config import DEFAULT_CONFIG, TrendFollowingConfig
from finance_analysis.trend_following.models import StrategyDecision
from finance_analysis.trend_following.risk import initial_risk_levels, next_add_price, trailing_stop

ACTIVE_STATES = {"ENTRY", "PYRAMIDING", "HOLDING", "WEAKENING", "REDUCE"}


def transition_state(
    row: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    *,
    trade_date: date,
    market_regime: str,
    config: TrendFollowingConfig = DEFAULT_CONFIG,
) -> StrategyDecision:
    close = float(row["reference_price"])
    atr = float(row["atr20"])
    candidate = bool(row["is_candidate"])
    prior_state = str(previous.get("state")) if previous else "IDLE"
    active = previous is not None and prior_state in ACTIVE_STATES and int(previous.get("units") or 0) > 0
    reasons: list[str] = []
    if not active:
        if candidate and market_regime != "RISK_OFF":
            levels = initial_risk_levels(close, atr, float(row["recent_structure_low"]), config)
            reasons.extend(["candidate thresholds passed", f"market regime permits entry: {market_regime}"])
            return StrategyDecision(
                "ENTRY", "ENTRY", close, close, 1, close, levels["initial_stop"],
                trailing_stop(close, atr, config), next_add_price(close, atr, config), levels["initial_stop"],
                trade_date, levels["suggested_initial_weight"], levels["suggested_max_weight"], reasons,
            )
        if candidate:
            reasons.extend(["candidate thresholds passed", "RISK_OFF blocks new entry"])
            state = "CANDIDATE"
        elif row["trend_candidate"]:
            reasons.append("hard trend filter passed")
            state = "WATCHING"
        else:
            reasons.append("hard trend filter not passed")
            state = "IDLE"
        return StrategyDecision(state, "WATCH", None, None, 0, None, None, None, None, None, None, None, None, reasons)

    entry = float(previous["entry_price"])
    last_add = float(previous.get("last_add_price") or entry)
    units = int(previous.get("units") or 1)
    highest = max(float(previous.get("highest_close") or entry), close)
    initial_stop = float(previous["initial_stop"])
    trailing = trailing_stop(highest, atr, config)
    previous_low = float(row["previous_low_10"])
    exit_level = max(initial_stop, trailing, previous_low)
    opened_at = previous.get("opened_at")
    initial_weight = previous.get("suggested_initial_weight")
    max_weight = previous.get("suggested_max_weight") or config.single_stock_max_weight
    if close <= initial_stop or close <= trailing or close < previous_low:
        reasons.append("price crossed initial, trailing, or previous 10D low exit level")
        return StrategyDecision(
            "EXIT", "EXIT", entry, last_add, 0, highest, initial_stop, trailing, None, exit_level,
            opened_at, initial_weight, max_weight, reasons,
        )
    weak = row["trend_score"] < config.add_trend_score or row["rs_score"] < config.add_rs_score or close < row["ma10"]
    reduce = close < row["ma10"] and row["rs_score"] < config.reduce_rs_score
    if reduce:
        reasons.append("close below MA10 and relative strength weakened")
        action, state = "REDUCE", "REDUCE"
    elif weak or market_regime == "RISK_OFF":
        reasons.append("additional units blocked by trend, relative strength, MA10, or regime")
        action, state = "STOP_ADD", "WEAKENING"
    elif units < config.max_units and close >= next_add_price(last_add, atr, config):
        units += 1
        last_add = close
        reasons.append("price advanced by the configured ATR pyramid interval")
        action, state = "ADD", "PYRAMIDING"
    else:
        reasons.append("active trend remains above risk exits")
        action, state = "HOLD", "HOLDING"
    return StrategyDecision(
        state, action, entry, last_add, units, highest, initial_stop, trailing,
        next_add_price(last_add, atr, config) if units < config.max_units else None,
        exit_level, opened_at, initial_weight, max_weight, reasons,
    )


__all__ = ["ACTIVE_STATES", "transition_state"]
