"""Point-in-time theoretical strategy state transitions."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from .config import DEFAULT_CONFIG, TrendFollowingConfig
from .models import StrategyDecision
from .risk import (
    can_add_unit,
    initial_risk_levels,
    next_add_price,
    theoretical_position_weight,
    trailing_stop,
)

ACTIVE_STATES = {"ENTRY", "PYRAMIDING", "HOLDING", "WEAKENING", "REDUCE"}
EXPANSION_ACTIONS = {"ENTRY", "ADD"}
PENDING_ACTIONS = {"ADD", "REDUCE", "EXIT"}


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
        "pending_action": None,
        "pending_since": None,
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


def _fresh_uninvested(
    row: Mapping[str, Any],
    *,
    trade_date: date,
    market_regime: str,
    reasons: list[str],
    blocked_action: str | None = None,
) -> StrategyDecision:
    """Expire an old entry signal and optionally create a new close signal."""
    if bool(row["is_candidate"]):
        permitted = market_regime != "RISK_OFF"
        return _decision(
            state="CANDIDATE",
            action=blocked_action or ("PENDING_ENTRY" if permitted else "WATCH"),
            signal_date=trade_date,
            signal_price=float(row["reference_price"]),
            pending_action="ENTRY" if permitted else None,
            pending_since=trade_date if permitted else None,
            reasons=[
                *reasons,
                "fresh candidate generated from current close",
                *([] if permitted else ["RISK_OFF blocks the fresh entry signal"]),
            ],
        )
    state = "WATCHING" if bool(row["trend_candidate"]) else "IDLE"
    return _decision(state=state, action=blocked_action or "WATCH", reasons=reasons)


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
    pending = str(previous.get("pending_action") or "") if previous else ""
    pending_entry = (
        previous is not None
        and prior_state == "CANDIDATE"
        and (
            pending == "ENTRY"
            or (pending == "" and str(previous.get("action") or "") == "PENDING_ENTRY")
        )
        and config.candidate_expiry_sessions >= 1
    )
    active = previous is not None and prior_state in ACTIVE_STATES and int(previous.get("units") or 0) > 0
    reasons: list[str] = []

    if pending_entry:
        signal_date = previous.get("signal_date") or previous.get("trade_date")
        signal_price = previous.get("signal_price")
        if signal_price is None:
            signal_price = previous.get("reference_price")
        if market_regime == "RISK_OFF":
            return _fresh_uninvested(
                row,
                trade_date=trade_date,
                market_regime=market_regime,
                reasons=["previous entry signal expired", "RISK_OFF blocks execution"],
            )
        entry = _open_price(row)
        signal_atr = float(previous.get("atr") or atr)
        previous_features = previous.get("features") or {}
        structure_low = float(previous_features.get("recent_structure_low") or row["recent_structure_low"])
        levels = initial_risk_levels(entry, signal_atr, structure_low, config)
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
            next_add_price=next_add_price(entry, signal_atr, config),
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
            return _fresh_uninvested(
                row,
                trade_date=trade_date,
                market_regime=market_regime,
                reasons=["candidate thresholds passed"],
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

    if pending == "EXIT":
        reasons.append("previous close exit signal executed at current open")
        return _decision(
            state="EXIT",
            action="EXIT",
            **{**shared, "units": 0, "next_add_price": None},
            reasons=reasons,
        )
    if pending == "REDUCE":
        reduced_units = max(units - 1, 0)
        reasons.append("previous close reduce signal executed at current open")
        if reduced_units == 0:
            return _decision(
                state="EXIT",
                action="EXIT",
                **{**shared, "units": 0, "next_add_price": None},
                reasons=reasons,
            )
        return _decision(
            state="REDUCE",
            action="REDUCE",
            **{**shared, "units": reduced_units},
            reasons=reasons,
        )
    if pending == "ADD":
        if market_regime == "RISK_OFF":
            reasons.append("previous add signal expired because RISK_OFF blocks execution")
            return _decision(
                state="WEAKENING",
                action="STOP_ADD",
                **shared,
                reasons=reasons,
            )
        add_price = _open_price(row)
        signal_atr = float(previous.get("atr") or atr)
        new_units = units + 1
        reasons.append("previous close add signal executed at current open")
        return _decision(
            state="PYRAMIDING",
            action="ADD",
            **{
                **shared,
                "last_add_price": add_price,
                "units": new_units,
                "next_add_price": (
                    next_add_price(add_price, signal_atr, config) if new_units < config.max_units else None
                ),
            },
            reasons=reasons,
        )

    if close <= initial_stop or close <= trailing or close < previous_low:
        reasons.append("close exit signal will execute at next-session open")
        return _decision(
            state="WEAKENING",
            action="PENDING_EXIT",
            **shared,
            pending_action="EXIT",
            pending_since=trade_date,
            reasons=reasons,
        )
    weak = row["trend_score"] < config.add_trend_score or row["rs_score"] < config.add_rs_score or close < row["ma10"]
    reduce = close < row["ma10"] and row["rs_score"] < config.reduce_rs_score
    if reduce:
        reasons.append("close reduce signal will execute at next-session open")
        return _decision(
            state="WEAKENING",
            action="PENDING_REDUCE",
            **shared,
            pending_action="REDUCE",
            pending_since=trade_date,
            reasons=reasons,
        )
    if weak or market_regime == "RISK_OFF":
        reasons.append("additional units blocked by trend, relative strength, MA10, or regime")
        return _decision(state="WEAKENING", action="STOP_ADD", **shared, reasons=reasons)
    if units < config.max_units and persisted_next_add is not None and close >= persisted_next_add:
        reasons.append("close add signal will execute at next-session open")
        return _decision(
            state="HOLDING",
            action="PENDING_ADD",
            **shared,
            pending_action="ADD",
            pending_since=trade_date,
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
    market_regime: str = "RISK_ON",
) -> dict[str, StrategyDecision]:
    """Allocate expansions using only persisted signal-day priority and theoretical positions."""
    approved: dict[str, StrategyDecision] = {}
    expansions: list[tuple[Mapping[str, Any], StrategyDecision]] = []
    exposure = 0.0
    ranked_codes = {str(row["code"]) for row in ranked}

    # Active codes with no current data remain part of the theoretical portfolio.
    for code, prior in previous.items():
        if code in ranked_codes or prior is None:
            continue
        if str(prior.get("state")) in ACTIVE_STATES and int(prior.get("units") or 0) > 0:
            exposure += theoretical_position_weight(
                prior.get("units"),
                prior.get("suggested_initial_weight"),
                prior.get("suggested_max_weight"),
            )

    for row in ranked:
        code = str(row["code"])
        decision = decisions[code]
        if decision.action in EXPANSION_ACTIONS:
            expansions.append((row, decision))
            continue
        exposure += theoretical_position_weight(
            decision.units,
            decision.suggested_initial_weight,
            decision.suggested_max_weight,
        )
        approved[code] = decision

    def expansion_priority(item: tuple[Mapping[str, Any], StrategyDecision]) -> tuple[float, int, str]:
        row, _decision_item = item
        prior = previous.get(str(row["code"])) or {}
        return (
            -float(prior.get("alpha_score") or 0.0),
            int(prior.get("rank") or 2**31 - 1),
            str(row["code"]),
        )

    expansions.sort(key=expansion_priority)
    cap = float(max_exposure)
    for row, decision in expansions:
        code = str(row["code"])
        prior = previous.get(code)
        if decision.action == "ADD" and prior is not None:
            existing = theoretical_position_weight(
                prior.get("units"),
                prior.get("suggested_initial_weight"),
                prior.get("suggested_max_weight"),
            )
        else:
            existing = 0.0
        increment = max(0.0, float(decision.suggested_initial_weight or 0.0))
        stock_cap_allows = decision.action != "ADD" or can_add_unit(
            prior.get("units") if prior else 0,
            decision.suggested_initial_weight,
            decision.suggested_max_weight,
        )
        if stock_cap_allows and exposure + existing + increment <= cap + 1e-12:
            exposure += existing + increment
            approved[code] = decision
            continue
        exposure += existing
        if decision.action == "ENTRY":
            approved[code] = _fresh_uninvested(
                row,
                trade_date=decision.opened_at or date.min,
                market_regime=market_regime,
                blocked_action="EXPOSURE_BLOCKED",
                reasons=[*decision.reasons, "portfolio exposure cap blocks entry; old signal expired"],
            )
        else:
            reason = (
                "single-stock max weight blocks add"
                if not stock_cap_allows
                else "portfolio exposure cap blocks add"
            )
            approved[code] = _replace(
                decision,
                state=(
                    str(prior.get("state"))
                    if prior and str(prior.get("state")) in {"HOLDING", "WEAKENING"}
                    else "HOLDING"
                ),
                action="EXPOSURE_BLOCKED",
                units=int((prior or {}).get("units") or decision.units - 1 or 0),
                last_add_price=(prior or {}).get("last_add_price", decision.last_add_price),
                next_add_price=(prior or {}).get("next_add_price", decision.next_add_price),
                pending_action=None,
                pending_since=None,
                reasons=[*decision.reasons, reason],
            )
    return approved


__all__ = ["ACTIVE_STATES", "apply_exposure_gate", "transition_state"]
