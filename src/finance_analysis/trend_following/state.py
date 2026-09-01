"""Two-phase, point-in-time theoretical strategy state transitions."""

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
EXECUTED_ACTIONS = {"ENTRY", "ADD", "REDUCE"}
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
        "pending_action": None,
        "pending_since": None,
        "pending_regime": None,
        "pending_max_exposure": None,
    }
    payload.update(kwargs)
    return StrategyDecision(**payload)


def _replace(decision: StrategyDecision, **changes: Any) -> StrategyDecision:
    payload = decision.to_dict()
    payload.update(changes)
    return StrategyDecision(**payload)


def _open_price(row: Mapping[str, Any]) -> float:
    if row.get("open") is None:
        raise ValueError("Trend Following execution requires the session open")
    return float(row["open"])


def _active_from_previous(previous: Mapping[str, Any], config: TrendFollowingConfig) -> StrategyDecision:
    entry = float(previous["entry_price"])
    return _decision(
        state=str(previous["state"]),
        action="HOLD",
        entry_price=entry,
        last_add_price=float(previous.get("last_add_price") or entry),
        units=int(previous.get("units") or 0),
        highest_close=float(previous.get("highest_close") or entry),
        initial_stop=float(previous["initial_stop"]),
        trailing_stop=None if previous.get("trailing_stop") is None else float(previous["trailing_stop"]),
        next_add_price=(
            None if previous.get("next_add_price") is None else float(previous["next_add_price"])
        ),
        exit_level=None if previous.get("exit_level") is None else float(previous["exit_level"]),
        opened_at=previous.get("opened_at"),
        suggested_initial_weight=previous.get("suggested_initial_weight"),
        suggested_max_weight=previous.get("suggested_max_weight") or config.single_stock_max_weight,
        signal_date=previous.get("signal_date"),
        signal_price=previous.get("signal_price"),
        reasons=[],
    )


def _pending_context(
    previous: Mapping[str, Any],
    config: TrendFollowingConfig,
) -> tuple[str, float]:
    regime = str(previous.get("pending_regime") or previous.get("market_regime") or "RISK_OFF")
    cap = previous.get("pending_max_exposure")
    if cap is None:
        cap = config.regime_max_exposure.get(regime, 0.0)
    return regime, float(cap)


def execute_pending_at_open(
    row: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    *,
    trade_date: date,
    config: TrendFollowingConfig = DEFAULT_CONFIG,
) -> StrategyDecision:
    """Phase 1: execute only information persisted by the previous close."""
    if previous is None:
        return _decision()

    prior_state = str(previous.get("state") or "IDLE")
    pending = str(previous.get("pending_action") or "")
    legacy_entry = pending == "" and str(previous.get("action") or "") == "PENDING_ENTRY"
    if prior_state == "CANDIDATE" and (pending == "ENTRY" or legacy_entry):
        pending_regime, _ = _pending_context(previous, config)
        if pending_regime == "RISK_OFF":
            return _decision(reasons=["pending entry expired because its signal regime was RISK_OFF"])
        entry = _open_price(row)
        signal_atr = float(previous.get("atr") or 0.0)
        previous_features = previous.get("features") or {}
        structure_low = float(
            previous_features.get("recent_structure_low")
            or entry - config.initial_stop_atr * signal_atr
        )
        levels = initial_risk_levels(entry, signal_atr, structure_low, config)
        signal_price = previous.get("signal_price") or previous.get("reference_price")
        initial_trailing = trailing_stop(max(entry, float(signal_price or entry)), signal_atr, config)
        return _decision(
            state="ENTRY",
            action="ENTRY",
            entry_price=entry,
            last_add_price=entry,
            units=1,
            highest_close=max(entry, float(signal_price or entry)),
            initial_stop=levels["initial_stop"],
            trailing_stop=initial_trailing,
            next_add_price=next_add_price(entry, signal_atr, config),
            exit_level=max(levels["initial_stop"], initial_trailing),
            opened_at=trade_date,
            suggested_initial_weight=levels["suggested_initial_weight"],
            suggested_max_weight=levels["suggested_max_weight"],
            signal_date=previous.get("signal_date") or previous.get("trade_date"),
            signal_price=None if signal_price is None else float(signal_price),
            reasons=["previous close entry signal executed at current open"],
        )

    active = prior_state in ACTIVE_STATES and int(previous.get("units") or 0) > 0
    if not active:
        return _decision(reasons=["previous entry signal expired"])

    base = _active_from_previous(previous, config)
    if pending == "EXIT":
        return _replace(
            base,
            state="EXIT",
            action="EXIT",
            units=0,
            next_add_price=None,
            reasons=["previous close exit signal executed at current open"],
        )
    if pending == "REDUCE":
        reduced_units = max(base.units - 1, 0)
        if reduced_units == 0:
            return _replace(
                base,
                state="EXIT",
                action="EXIT",
                units=0,
                next_add_price=None,
                reasons=["previous close reduce signal closed the final unit at current open"],
            )
        return _replace(
            base,
            state="REDUCE",
            action="REDUCE",
            units=reduced_units,
            reasons=["previous close reduce signal executed at current open"],
        )
    if pending == "ADD":
        pending_regime, _ = _pending_context(previous, config)
        if pending_regime == "RISK_OFF":
            return _replace(
                base,
                state="WEAKENING",
                action="EXPOSURE_BLOCKED",
                reasons=["pending add expired because its signal regime was RISK_OFF"],
            )
        add_price = _open_price(row)
        signal_atr = float(previous.get("atr") or 0.0)
        new_units = base.units + 1
        return _replace(
            base,
            state="PYRAMIDING",
            action="ADD",
            units=new_units,
            last_add_price=add_price,
            next_add_price=(
                next_add_price(add_price, signal_atr, config) if new_units < config.max_units else None
            ),
            reasons=["previous close add signal executed at current open"],
        )
    return base


def _signal_context(
    action: str,
    *,
    trade_date: date,
    market_regime: str,
    max_exposure: float,
) -> dict[str, Any]:
    return {
        "pending_action": action,
        "pending_since": trade_date,
        "pending_regime": market_regime,
        "pending_max_exposure": float(max_exposure),
    }


def evaluate_close(
    row: Mapping[str, Any],
    open_decision: StrategyDecision,
    *,
    trade_date: date,
    market_regime: str,
    max_exposure: float,
    config: TrendFollowingConfig = DEFAULT_CONFIG,
) -> StrategyDecision:
    """Phase 2: evaluate the current close and persist the next session's action."""
    if open_decision.action == "EXIT":
        return open_decision

    if open_decision.units <= 0:
        if bool(row["is_candidate"]) and market_regime != "RISK_OFF":
            return _decision(
                state="CANDIDATE",
                action=open_decision.action if open_decision.action == "EXPOSURE_BLOCKED" else "WATCH",
                signal_date=trade_date,
                signal_price=float(row["reference_price"]),
                **_signal_context(
                    "ENTRY",
                    trade_date=trade_date,
                    market_regime=market_regime,
                    max_exposure=max_exposure,
                ),
                reasons=[*open_decision.reasons, "fresh candidate generated from current close"],
            )
        state = "WATCHING" if bool(row["trend_candidate"]) else "IDLE"
        reasons = [*open_decision.reasons]
        reasons.append(
            "RISK_OFF blocks a new entry signal"
            if bool(row["is_candidate"])
            else "current close did not produce an entry setup"
        )
        return _decision(state=state, action="WATCH", reasons=reasons)

    close = float(row["reference_price"])
    atr = float(row["atr20"])
    highest = max(float(open_decision.highest_close or open_decision.entry_price or close), close)
    initial_stop = float(open_decision.initial_stop)
    trailing = trailing_stop(
        highest,
        atr,
        config,
        previous_stop=open_decision.trailing_stop,
    )
    previous_low = float(row["previous_low_10"])
    exit_level = max(initial_stop, trailing, previous_low)
    next_add = open_decision.next_add_price
    updated = _replace(
        open_decision,
        highest_close=highest,
        trailing_stop=trailing,
        exit_level=exit_level,
        pending_action=None,
        pending_since=None,
        pending_regime=None,
        pending_max_exposure=None,
    )
    executed = open_decision.action in EXECUTED_ACTIONS
    stable_state = {
        "ENTRY": "ENTRY",
        "ADD": "PYRAMIDING",
        "REDUCE": "REDUCE",
    }.get(open_decision.action, "HOLDING")
    observation_action = open_decision.action if executed else (
        "EXPOSURE_BLOCKED" if open_decision.action == "EXPOSURE_BLOCKED" else "HOLD"
    )

    if close <= initial_stop or close <= trailing or close < previous_low:
        return _replace(
            updated,
            state=stable_state if executed else "WEAKENING",
            action=observation_action,
            **_signal_context(
                "EXIT",
                trade_date=trade_date,
                market_regime=market_regime,
                max_exposure=max_exposure,
            ),
            reasons=[*updated.reasons, "current close generated a next-open exit signal"],
        )

    weak = (
        row["trend_score"] < config.add_trend_score
        or row["rs_score"] < config.add_rs_score
        or close < row["ma10"]
    )
    reduce = close < row["ma10"] and row["rs_score"] < config.reduce_rs_score
    if reduce:
        return _replace(
            updated,
            state=stable_state if executed else "WEAKENING",
            action=observation_action,
            **_signal_context(
                "REDUCE",
                trade_date=trade_date,
                market_regime=market_regime,
                max_exposure=max_exposure,
            ),
            reasons=[*updated.reasons, "current close generated a next-open reduce signal"],
        )
    if weak or market_regime == "RISK_OFF":
        return _replace(
            updated,
            state=stable_state if executed else "WEAKENING",
            action=observation_action if executed else "STOP_ADD",
            reasons=[
                *updated.reasons,
                "current close blocks new add signals by trend, relative strength, MA10, or regime",
            ],
        )
    if open_decision.units < config.max_units and next_add is not None and close >= next_add:
        return _replace(
            updated,
            state=stable_state,
            action=observation_action,
            **_signal_context(
                "ADD",
                trade_date=trade_date,
                market_regime=market_regime,
                max_exposure=max_exposure,
            ),
            reasons=[*updated.reasons, "current close generated a next-open add signal"],
        )
    return _replace(
        updated,
        state=stable_state,
        action=observation_action,
        reasons=[*updated.reasons, "active trend remains above risk exits"],
    )


def transition_state(
    row: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    *,
    trade_date: date,
    market_regime: str,
    max_exposure: float | None = None,
    config: TrendFollowingConfig = DEFAULT_CONFIG,
) -> StrategyDecision:
    """Execute previous context at open, then evaluate current close."""
    exposure = (
        config.regime_max_exposure[market_regime]
        if max_exposure is None
        else float(max_exposure)
    )
    opened = execute_pending_at_open(row, previous, trade_date=trade_date, config=config)
    return evaluate_close(
        row,
        opened,
        trade_date=trade_date,
        market_regime=market_regime,
        max_exposure=exposure,
        config=config,
    )


def apply_exposure_gate(
    ranked: list[Mapping[str, Any]],
    decisions: Mapping[str, StrategyDecision],
    previous: Mapping[str, Mapping[str, Any] | None],
    *,
    max_exposure: float | None = None,
    config: TrendFollowingConfig = DEFAULT_CONFIG,
) -> dict[str, StrategyDecision]:
    """Approve open expansions using only each previous snapshot's persisted context."""
    approved: dict[str, StrategyDecision] = {}
    expansions: list[tuple[Mapping[str, Any], StrategyDecision]] = []
    exposure = 0.0
    ranked_codes = {str(row["code"]) for row in ranked}

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

    expansions.sort(
        key=lambda item: (
            -float((previous.get(str(item[0]["code"])) or {}).get("alpha_score") or 0.0),
            int((previous.get(str(item[0]["code"])) or {}).get("rank") or 2**31 - 1),
            str(item[0]["code"]),
        )
    )
    for row, decision in expansions:
        code = str(row["code"])
        prior = previous.get(code) or {}
        if prior.get("pending_max_exposure") is not None:
            execution_cap = float(prior["pending_max_exposure"])
        elif prior.get("pending_regime") is not None or prior.get("market_regime") is not None:
            _, execution_cap = _pending_context(prior, config)
        else:
            execution_cap = 0.0 if max_exposure is None else float(max_exposure)
        existing = (
            theoretical_position_weight(
                prior.get("units"),
                prior.get("suggested_initial_weight"),
                prior.get("suggested_max_weight"),
            )
            if decision.action == "ADD"
            else 0.0
        )
        increment = max(0.0, float(decision.suggested_initial_weight or 0.0))
        stock_cap_allows = decision.action != "ADD" or (
            decision.units <= config.max_units
            and can_add_unit(
                prior.get("units"),
                decision.suggested_initial_weight,
                decision.suggested_max_weight,
            )
        )
        if stock_cap_allows and exposure + existing + increment <= execution_cap + 1e-12:
            exposure += existing + increment
            approved[code] = decision
            continue

        exposure += existing
        if decision.action == "ENTRY":
            approved[code] = _decision(
                action="EXPOSURE_BLOCKED",
                reasons=[*decision.reasons, "persisted execution exposure cap blocks entry"],
            )
            continue
        reason = (
            "single-stock max weight blocks add"
            if not stock_cap_allows
            else "persisted execution exposure cap blocks add"
        )
        approved[code] = _replace(
            _active_from_previous(prior, config),
            action="EXPOSURE_BLOCKED",
            reasons=[*decision.reasons, reason],
        )
    return approved


def apply_regime_exposure_reduction(
    ranked: list[Mapping[str, Any]],
    decisions: Mapping[str, StrategyDecision],
    *,
    trade_date: date,
    market_regime: str,
    max_exposure: float,
    previous: Mapping[str, Mapping[str, Any] | None] | None = None,
) -> dict[str, StrategyDecision]:
    """Schedule one-unit reductions in the weakest holdings until the regime cap is approached."""
    adjusted = dict(decisions)
    if market_regime != "RISK_OFF":
        return adjusted

    exposure = 0.0
    for decision in decisions.values():
        projected_units = (
            0
            if decision.pending_action == "EXIT"
            else max(decision.units - 1, 0)
            if decision.pending_action == "REDUCE"
            else decision.units
        )
        exposure += theoretical_position_weight(
            projected_units,
            decision.suggested_initial_weight,
            decision.suggested_max_weight,
        )
    for code, prior in (previous or {}).items():
        if code in decisions or prior is None:
            continue
        if str(prior.get("state")) in ACTIVE_STATES and int(prior.get("units") or 0) > 0:
            pending = str(prior.get("pending_action") or "")
            projected_units = (
                0
                if pending == "EXIT"
                else max(int(prior.get("units") or 0) - 1, 0)
                if pending == "REDUCE"
                else int(prior.get("units") or 0)
            )
            exposure += theoretical_position_weight(
                projected_units,
                prior.get("suggested_initial_weight"),
                prior.get("suggested_max_weight"),
            )
    if exposure <= max_exposure + 1e-12:
        return adjusted

    row_by_code = {str(row["code"]): row for row in ranked}
    reducible = [
        (code, decision)
        for code, decision in decisions.items()
        if decision.units > 0 and decision.pending_action not in {"EXIT", "REDUCE"}
    ]
    reducible.sort(
        key=lambda item: (
            float(row_by_code.get(item[0], {}).get("alpha_score") or 0.0),
            -int(row_by_code.get(item[0], {}).get("rank") or 0),
            item[0],
        )
    )
    for code, decision in reducible:
        if exposure <= max_exposure + 1e-12:
            break
        current_weight = theoretical_position_weight(
            decision.units,
            decision.suggested_initial_weight,
            decision.suggested_max_weight,
        )
        reduced_weight = theoretical_position_weight(
            max(decision.units - 1, 0),
            decision.suggested_initial_weight,
            decision.suggested_max_weight,
        )
        exposure -= current_weight - reduced_weight
        adjusted[code] = _replace(
            decision,
            **_signal_context(
                "REDUCE",
                trade_date=trade_date,
                market_regime=market_regime,
                max_exposure=max_exposure,
            ),
            reasons=[
                *decision.reasons,
                "RISK_OFF exposure exceeds 20%; scheduled a one-unit next-open reduction",
            ],
        )
    return adjusted


__all__ = [
    "ACTIVE_STATES",
    "apply_exposure_gate",
    "apply_regime_exposure_reduction",
    "evaluate_close",
    "execute_pending_at_open",
    "transition_state",
]
