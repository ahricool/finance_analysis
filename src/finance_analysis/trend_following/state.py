"""Point-in-time theoretical strategy state transitions."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from .config import DEFAULT_CONFIG, TrendFollowingConfig
from .models import StrategyDecision
from .risk import (
    initial_risk_levels,
    next_add_price,
    position_weight,
    trailing_stop,
)

ACTIVE_STATES = {"ENTRY", "PYRAMIDING", "HOLDING", "WEAKENING", "REDUCE"}
EXPANSION_ACTIONS = {"ENTRY", "ADD"}


def _decision(**kwargs: Any) -> StrategyDecision:
    payload = {
        "state": "IDLE",
        "action": "WATCH",
        "entry_price": None,
        "last_add_price": None,
        "units": 0,
        "highest_close": None,
        "initial_stop": None,
        "trailing_stop": None,
        "next_add_price": None,
        "exit_level": None,
        "opened_at": None,
        "suggested_initial_weight": None,
        "suggested_max_weight": None,
        "reasons": [],
        "signal_date": None,
        "signal_price": None,
    }
    payload.update(kwargs)
    return StrategyDecision(**payload)


def _replace(decision: StrategyDecision, **changes: Any) -> StrategyDecision:
    payload = decision.to_dict()
    payload.update(changes)
    return StrategyDecision(**payload)


def _open_price(row: Mapping[str, Any]) -> float:
    if row.get("open") is not None:
        return float(row["open"])
    raise ValueError("Trend Following ENTRY requires the session open")


def _persisted_next_add(
    previous: Mapping[str, Any],
    last_add: float,
    atr: float,
    config: TrendFollowingConfig,
) -> float | None:
    stored = previous.get("next_add_price")
    if stored is not None:
        return float(stored)
    units = int(previous.get("units") or 0)
    if units <= 0 or units >= config.max_units:
        return None
    return next_add_price(last_add, atr, config)


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
    pending_entry = previous is not None and prior_state == "CANDIDATE"
    active = previous is not None and prior_state in ACTIVE_STATES and int(previous.get("units") or 0) > 0
    reasons: list[str] = []

    if pending_entry:
        signal_date = previous.get("signal_date") or previous.get("trade_date")
        signal_price = previous.get("signal_price")
        if signal_price is None:
            signal_price = previous.get("reference_price")
        if market_regime == "RISK_OFF":
            reasons.extend(["previous session produced a candidate", "RISK_OFF blocks new entry"])
            return _decision(
                state="CANDIDATE",
                action="WATCH",
                signal_date=signal_date,
                signal_price=None if signal_price is None else float(signal_price),
                reasons=reasons,
            )
        entry = _open_price(row)
        levels = initial_risk_levels(entry, atr, float(row["recent_structure_low"]), config)
        highest = close
        trailing = trailing_stop(highest, atr, config)
        exit_level = max(levels["initial_stop"], trailing, float(row["previous_low_10"]))
        reasons.extend([
            "previous session produced a candidate",
            f"theoretical fill at next-session open {entry}",
            f"market regime permits entry: {market_regime}",
        ])
        return _decision(
            state="ENTRY",
            action="ENTRY",
            entry_price=entry,
            last_add_price=entry,
            units=1,
            highest_close=highest,
            initial_stop=levels["initial_stop"],
            trailing_stop=trailing,
            next_add_price=next_add_price(entry, atr, config),
            exit_level=exit_level,
            opened_at=trade_date,
            suggested_initial_weight=levels["suggested_initial_weight"],
            suggested_max_weight=levels["suggested_max_weight"],
            signal_date=signal_date,
            signal_price=None if signal_price is None else float(signal_price),
            reasons=reasons,
        )

    if not active:
        if candidate:
            reasons.append("candidate thresholds passed")
            if market_regime == "RISK_OFF":
                reasons.append("RISK_OFF blocks new entry")
            else:
                reasons.append(f"market regime permits pending entry: {market_regime}")
            return _decision(
                state="CANDIDATE",
                action="WATCH" if market_regime == "RISK_OFF" else "PENDING_ENTRY",
                signal_date=trade_date,
                signal_price=close,
                reasons=reasons,
            )
        if row["trend_candidate"]:
            reasons.append("hard trend filter passed")
            state = "WATCHING"
        else:
            reasons.append("hard trend filter not passed")
            state = "IDLE"
        return _decision(state=state, action="WATCH", reasons=reasons)

    entry = float(previous["entry_price"])
    last_add = float(previous.get("last_add_price") or entry)
    units = int(previous.get("units") or 1)
    highest = max(float(previous.get("highest_close") or entry), close)
    initial_stop = float(previous["initial_stop"])
    trailing = trailing_stop(highest, atr, config, previous_stop=previous.get("trailing_stop"))
    previous_low = float(row["previous_low_10"])
    exit_level = max(initial_stop, trailing, previous_low)
    opened_at = previous.get("opened_at")
    initial_weight = previous.get("suggested_initial_weight")
    max_weight = previous.get("suggested_max_weight") or config.single_stock_max_weight
    signal_date = previous.get("signal_date")
    signal_price = previous.get("signal_price")
    persisted_next_add = _persisted_next_add(previous, last_add, atr, config)
    shared = dict(
        entry_price=entry,
        last_add_price=last_add,
        units=units,
        highest_close=highest,
        initial_stop=initial_stop,
        trailing_stop=trailing,
        next_add_price=persisted_next_add,
        exit_level=exit_level,
        opened_at=opened_at,
        suggested_initial_weight=initial_weight,
        suggested_max_weight=max_weight,
        signal_date=signal_date,
        signal_price=None if signal_price is None else float(signal_price),
    )
    if close <= initial_stop or close <= trailing or close < previous_low:
        reasons.append("price crossed initial, trailing, or previous 10D low exit level")
        return _decision(
            state="EXIT",
            action="EXIT",
            **{**shared, "units": 0, "next_add_price": None},
            reasons=reasons,
        )
    weak = row["trend_score"] < config.add_trend_score or row["rs_score"] < config.add_rs_score or close < row["ma10"]
    reduce = close < row["ma10"] and row["rs_score"] < config.reduce_rs_score
    if reduce:
        reasons.append("close below MA10 and relative strength weakened")
        return _decision(state="REDUCE", action="REDUCE", **shared, reasons=reasons)
    if weak or market_regime == "RISK_OFF":
        reasons.append("additional units blocked by trend, relative strength, MA10, or regime")
        return _decision(state="WEAKENING", action="STOP_ADD", **shared, reasons=reasons)
    if units < config.max_units and persisted_next_add is not None and close >= persisted_next_add:
        units += 1
        last_add = float(persisted_next_add)
        reasons.append("price reached the persisted ATR pyramid interval")
        return _decision(
            state="PYRAMIDING",
            action="ADD",
            **{
                **shared,
                "last_add_price": last_add,
                "units": units,
                "next_add_price": (
                    next_add_price(last_add, atr, config) if units < config.max_units else None
                ),
            },
            reasons=reasons,
        )
    reasons.append("active trend remains above risk exits")
    return _decision(state="HOLDING", action="HOLD", **shared, reasons=reasons)


def apply_exposure_gate(
    ranked: list[Mapping[str, Any]],
    decisions: Mapping[str, StrategyDecision],
    previous: Mapping[str, Mapping[str, Any] | None],
    *,
    max_exposure: float,
) -> dict[str, StrategyDecision]:
    """Approve ENTRY/ADD by alpha rank until theoretical exposure is filled."""
    approved: dict[str, StrategyDecision] = {}
    expansions: list[tuple[Mapping[str, Any], StrategyDecision]] = []
    exposure = 0.0
    for row in ranked:
        code = str(row["code"])
        decision = decisions[code]
        if decision.action in EXPANSION_ACTIONS:
            expansions.append((row, decision))
            continue
        exposure += position_weight(decision.units, decision.suggested_initial_weight)
        approved[code] = decision

    expansions.sort(key=lambda item: (-float(item[0]["alpha_score"]), str(item[0]["code"])))
    cap = float(max_exposure)
    for row, decision in expansions:
        code = str(row["code"])
        prior = previous.get(code)
        if decision.action == "ADD" and prior is not None:
            existing = position_weight(prior.get("units"), prior.get("suggested_initial_weight"))
        else:
            existing = 0.0
        increment = float(decision.suggested_initial_weight or 0.0)
        if exposure + existing + increment <= cap + 1e-12:
            exposure += existing + increment
            approved[code] = decision
            continue
        exposure += existing
        if decision.action == "ENTRY":
            approved[code] = _replace(
                decision,
                state="CANDIDATE",
                action="EXPOSURE_BLOCKED",
                entry_price=None,
                last_add_price=None,
                units=0,
                highest_close=None,
                initial_stop=None,
                trailing_stop=None,
                next_add_price=None,
                exit_level=None,
                opened_at=None,
                suggested_initial_weight=None,
                suggested_max_weight=None,
                reasons=[*decision.reasons, "portfolio exposure cap blocks entry"],
            )
        else:
            approved[code] = _replace(
                decision,
                state="HOLDING",
                action="EXPOSURE_BLOCKED",
                units=int((prior or {}).get("units") or decision.units - 1 or 0),
                last_add_price=(prior or {}).get("last_add_price", decision.last_add_price),
                next_add_price=(prior or {}).get("next_add_price", decision.next_add_price),
                reasons=[*decision.reasons, "portfolio exposure cap blocks add"],
            )
    return approved


__all__ = ["ACTIVE_STATES", "apply_exposure_gate", "transition_state"]
