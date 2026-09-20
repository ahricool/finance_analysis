# -*- coding: utf-8 -*-
"""exit_v1: Stage A/B/C, high watermark, active stop, ADDON-first soft reduce. No ActivePlan."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Sequence
from uuid import uuid4

from finance_analysis.core.time import coerce_aware_utc  # pragma: allowlist secret
from finance_analysis.portfolio.models import ResolvedLot, ResolvedPosition  # pragma: allowlist secret
from finance_analysis.trade_engine.bars import NormalizedBar, adjacent, expected_closed_ends, latest_expected_closed  # pragma: allowlist secret
from finance_analysis.trade_engine.config import RiskPolicy, get_risk_policy  # pragma: allowlist secret
from finance_analysis.trade_engine.indicators import annotate, ordinary_weak, recovered, severe_break  # pragma: allowlist secret
from finance_analysis.trade_engine.models import PositionContext, QuoteView, TradeSignalCandidate, one_candidate  # pragma: allowlist secret

STAGE_A = "A"
STAGE_B = "B"
STAGE_C = "C"
QUOTE_FUTURE_SKEW = timedelta(seconds=5)
KEY = "exit_v1"
VERSION = "1"


def fingerprint(lot_id: str, symbol: str, role: str, entry_price: Decimal, entry_time: datetime) -> str:
    aware = coerce_aware_utc(entry_time)
    return "|".join([lot_id, symbol, role, format(entry_price, "f"), aware.isoformat() if aware else ""])


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return coerce_aware_utc(value) or value
    return coerce_aware_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _stage(m: Decimal | None, policy: RiskPolicy) -> str:
    if m is None:
        return "UNKNOWN"
    if m < policy.stage_a_max:
        return STAGE_A
    if m < policy.stage_b_max:
        return STAGE_B
    return STAGE_C


def _capital_stop(entry: Decimal, policy: RiskPolicy) -> Decimal:
    return entry * (Decimal("1") - policy.capital_stop)


def _profit_stop(entry: Decimal, high: Decimal, stage: str, policy: RiskPolicy) -> Decimal | None:
    if stage == STAGE_B:
        return entry + policy.stage_b_lock * (high - entry)
    if stage == STAGE_C:
        return entry + policy.stage_c_lock * (high - entry)
    return None


def _structure_stop(bars_before: Sequence[NormalizedBar], entry: Decimal, policy: RiskPolicy) -> Decimal | None:
    if len(bars_before) < policy.structure_bars:
        return None
    window = list(bars_before)[-policy.structure_bars:]
    stop = min(bar.low for bar in window)
    if stop <= 0 or stop >= entry:
        return None
    return stop


def _max_stop(candidates: Sequence[Decimal | None]) -> Decimal | None:
    valid = [item for item in candidates if item is not None]
    return max(valid) if valid else None


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


def _evidence(row) -> dict:
    if row is None:
        return {}
    return {
        "bar_end": row.bar.bar_end.isoformat(),
        "close": format(row.bar.close, "f"),
        "ema20": None if row.ema20 is None else format(row.ema20, "f"),
        "vwap": None if row.vwap is None else format(row.vwap, "f"),
        "vwap_mode": row.vwap_mode,
        "previous_30m_low": None if row.previous_30m_low is None else format(row.previous_30m_low, "f"),
        "rvol": None if row.rvol is None else format(row.rvol, "f"),
    }


def _dump_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = coerce_aware_utc(value) or value
    return aware.isoformat()


def _dump_dec(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _update_lot(
    lot: ResolvedLot,
    existing: dict[str, Any] | None,
    bars: Sequence[NormalizedBar],
    policy: RiskPolicy,
    *,
    symbol: str,
    market: str,
) -> dict[str, Any]:
    mark = fingerprint(lot.lot_id, symbol, lot.role, lot.entry_price, lot.entry_time)
    after = [bar for bar in bars if bar.closed and bar.bar_end > lot.entry_time]
    before = [bar for bar in bars if bar.closed and bar.bar_end <= lot.entry_time]
    observed_from = after[0].bar_end if after else None
    high = None
    high_bar_end = None
    existing_high = _dec(existing.get("high_watermark")) if existing else None
    if after:
        high_bar = max(after, key=lambda bar: bar.close)
        high = high_bar.close
        high_bar_end = high_bar.bar_end
        if existing_high is not None and existing_high > high:
            high = existing_high
            high_bar_end = _dt(existing.get("stop_effective_at")) or high_bar_end
    elif existing_high is not None:
        high = existing_high
        high_bar_end = _dt(existing.get("stop_effective_at")) if existing else None
    m = None if high is None else (high / lot.entry_price) - Decimal("1")
    stage = _stage(m, policy)
    existing_stage = existing.get("profit_stage") if existing else None
    if existing_stage in {STAGE_B, STAGE_C}:
        order = {"UNKNOWN": 0, STAGE_A: 1, STAGE_B: 2, STAGE_C: 3}
        if order.get(stage, 0) < order[existing_stage]:
            stage = existing_stage
    structure = _dec(existing.get("structure_stop")) if existing else None
    if structure is None and lot.role == "ADDON":
        structure = _structure_stop(before, lot.entry_price, policy)
    capital = _capital_stop(lot.entry_price, policy)
    profit = _profit_stop(lot.entry_price, high, stage, policy) if high is not None and stage in {STAGE_B, STAGE_C} else None
    previous_stop = _dec(existing.get("active_stop")) if existing else None
    active = _max_stop([capital, structure, profit, previous_stop])
    stop_effective_at = _dt(existing.get("stop_effective_at")) if existing else None
    if active is not None and (previous_stop is None or active > previous_stop):
        stop_effective_at = high_bar_end or (after[-1].bar_end if after else None)
    last_end = after[-1].bar_end if after else None
    expected = expected_closed_ends(market, lot.entry_time, last_end) if last_end is not None else []
    present_ends = {bar.bar_end for bar in after}
    if not after:
        coverage, coverage_reason = "NONE", "no_post_entry_bars"
    elif expected and present_ends >= set(expected):
        coverage, coverage_reason = "FULL", None
    else:
        coverage, coverage_reason = "PARTIAL", "high_watermark_coverage_incomplete"
    return {
        "lot_id": lot.lot_id,
        "role": lot.role,
        "entry_price": _dump_dec(lot.entry_price),
        "entry_time": _dump_dt(lot.entry_time),
        "input_fingerprint": mark,
        "last_quantity": _dump_dec(lot.quantity),
        "high_watermark": _dump_dec(high),
        "profit_stage": stage,
        "active_stop": _dump_dec(active),
        "structure_stop": _dump_dec(structure),
        "observed_from": _dump_dt(observed_from),
        "coverage": coverage,
        "coverage_reason": coverage_reason,
        "stop_effective_at": _dump_dt(stop_effective_at),
    }


def _apply_soft_targets(
    lots: tuple[ResolvedLot, ...],
    lot_state: dict[str, dict[str, Any]],
    remaining: dict[str, Decimal],
    trigger_end: datetime | None,
) -> list[str]:
    reasons: list[str] = []
    addon_fail = [
        lot
        for lot in lots
        if lot.quantity > 0
        and lot.role == "ADDON"
        and lot_state[lot.lot_id].get("profit_stage") == STAGE_A
        and remaining[lot.lot_id] > 0
        and trigger_end is not None
        and lot.entry_time < trigger_end
    ]
    if addon_fail:
        for lot in addon_fail:
            remaining[lot.lot_id] = Decimal("0")
            reasons.append(f"{lot.lot_id}:未站稳加仓优先清零")
        return reasons
    stage_a = [lot for lot in lots if lot.quantity > 0 and lot_state[lot.lot_id].get("profit_stage") == STAGE_A]
    for lot in stage_a:
        remaining[lot.lot_id] = Decimal("0")
    profitable = [
        lot
        for lot in lots
        if lot.quantity > 0
        and lot_state[lot.lot_id].get("profit_stage") in {STAGE_B, STAGE_C}
        and remaining[lot.lot_id] > 0
    ]
    budget = sum((remaining[lot.lot_id] for lot in profitable), start=Decimal("0")) * Decimal("0.5")
    for lot in sorted(profitable, key=lambda item: item.entry_time, reverse=True):
        if budget <= 0:
            break
        take = min(remaining[lot.lot_id], budget)
        remaining[lot.lot_id] -= take
        budget -= take
    return reasons


def _action_for(target: Decimal, current: Decimal) -> str:
    if target <= 0 and current > 0:
        return "EXIT"
    if target < current:
        return "REDUCE"
    return "HOLD"


class ExitV1:
    key = KEY
    version = VERSION
    market = None

    def evaluate(self, context: PositionContext) -> list[TradeSignalCandidate]:
        position = context.position
        quote = context.quote
        bars = context.five_minute_bars
        state = context.strategy_state
        policy = context.policy or get_risk_policy()
        now = context.now
        latest_expected = context.latest_expected
        bars_stale = context.bars_stale
        if now is None:
            from finance_analysis.core.time import utc_now  # pragma: allowlist secret
            now = utc_now()
        market = position.market
        lots = position.lots or ()
        annotated = annotate(list(bars), policy=policy, market=market, now=now)
        closed = [row for row in annotated if row.bar.closed]
        expected = latest_expected if latest_expected is not None else latest_expected_closed(market, now)
        existing_lots = state.get("lots") or {}
        lot_state = {
            lot.lot_id: _update_lot(
                lot,
                existing_lots.get(lot.lot_id),
                [row.bar for row in closed],
                policy,
                symbol=position.symbol,
                market=market,
            )
            for lot in lots
        }
        quote_status = _quote_status(quote, now)
        remaining = {lot.lot_id: lot.quantity for lot in lots}
        hard_reasons: dict[str, str] = {}
        reasons: list[str] = []
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
                    hard_reasons[lot.lot_id] = "hard_stop"
                    reasons.append(f"{lot.lot_id}:报价触及保护价")

        five_status = "UNAVAILABLE"
        if not closed:
            five_status = "UNAVAILABLE"
        elif bars_stale:
            five_status = "STALE"
        else:
            last_end = closed[-1].bar.bar_end
            if expected is not None and last_end < expected:
                five_status = "STALE"
            else:
                five_status = "OK"

        last_hard_target = _dec(state.get("last_hard_target"))
        if last_hard_target is not None and last_hard_target <= 0:
            for lot in lots:
                remaining[lot.lot_id] = Decimal("0")

        weak_streak = int(state.get("weak_streak") or 0)
        recovery_streak = int(state.get("recovery_streak") or 0)
        episode_id = state.get("soft_episode_id")
        episode_active = bool(state.get("soft_episode_active"))
        last_vwap = state.get("last_vwap_mode")
        last_bar_end = _dt(state.get("last_processed_5m_bar"))
        restoring = last_bar_end is None
        allow_soft = five_status == "OK" and not bars_stale
        new_soft = False
        soft_trigger = None
        recovered_now = False
        watch_now = False
        earliest_entry = min((lot.entry_time for lot in lots if lot.quantity > 0), default=now)

        decision_rows = []
        if allow_soft:
            for row in closed:
                if last_bar_end is not None and row.bar.bar_end <= last_bar_end:
                    continue
                if row.bar.bar_end <= earliest_entry:
                    last_bar_end = row.bar.bar_end
                    continue
                decision_rows.append(row)
        previous_row = None
        if decision_rows:
            prior = [row for row in closed if row.bar.bar_end < decision_rows[0].bar.bar_end]
            previous_row = prior[-1] if prior else None

        for row in decision_rows:
            if last_vwap and row.vwap_mode != last_vwap:
                weak_streak = 0
                recovery_streak = 0
            last_vwap = row.vwap_mode
            if row.gap_before:
                weak_streak = 0
                recovery_streak = 0
            last_bar_end = row.bar.bar_end
            if row.opening_observation:
                previous_row = row
                continue
            is_current = expected is not None and row.bar.bar_end == expected
            can_emit = (not restoring or is_current) and is_current
            weak = ordinary_weak(row, policy)
            is_severe = severe_break(row, policy)
            if is_severe is True:
                weak_streak = 2
                recovery_streak = 0
                if can_emit and not episode_active:
                    new_soft = True
                    if episode_id is None:
                        episode_id = uuid4().hex
                    reasons.append("严重破位单根确认")
                    soft_trigger = row
                previous_row = row
                continue
            if weak is True:
                if previous_row is not None and adjacent(previous_row.bar, row.bar) and weak_streak >= 1:
                    weak_streak += 1
                else:
                    weak_streak = 1
                recovery_streak = 0
                if weak_streak == 1:
                    watch_now = True
                    reasons.append("普通走弱观察")
                elif weak_streak >= 2 and can_emit and not episode_active:
                    new_soft = True
                    if episode_id is None:
                        episode_id = uuid4().hex
                    reasons.append("相邻两根确认走弱")
                    soft_trigger = row
            else:
                weak_streak = 0
            if previous_row is not None:
                rec = recovered(previous_row, row)
                if rec is True:
                    recovery_streak += 1
                    if episode_id or episode_active:
                        reasons.append("相邻两根确认恢复")
                        recovered_now = True
                        episode_id = None
                        episode_active = False
                        weak_streak = 0
                        recovery_streak = 0
                        state["last_soft_signal_key"] = None
                        state["last_soft_target"] = None
                        state["last_confirmed_soft_signal_key"] = None
                        state["last_confirmed_soft_target"] = None
                else:
                    recovery_streak = 0
            previous_row = row

        current_qty = sum((lot.quantity for lot in lots), start=Decimal("0"))
        signals: list[TradeSignalCandidate] = []
        last_soft_target = _dec(state.get("last_confirmed_soft_target")) or _dec(state.get("last_soft_target"))
        target = sum(remaining.values(), start=Decimal("0"))

        if new_soft and episode_active:
            new_soft = False
            reasons.append("同一episode不再重复软减仓")

        if new_soft:
            trigger_row = soft_trigger or (decision_rows[-1] if decision_rows else None)
            trigger_end = trigger_row.bar.bar_end if trigger_row is not None else expected
            reasons.extend(_apply_soft_targets(lots, lot_state, remaining, trigger_end))
            target = sum(remaining.values(), start=Decimal("0"))
            action = _action_for(target, current_qty)
            signal_key = f"exit_v1:{position.position_id}:{episode_id}:{action}:{format(target, 'f')}"
            if action != "HOLD" and signal_key != state.get("last_confirmed_soft_signal_key"):
                evidence = _evidence(trigger_row)
                evidence.update(
                    {
                        "rule_version": policy.rule_version,
                        "five_minute_status": five_status,
                        "quote_status": quote_status,
                        "profit_stage": _position_stage(lot_state),
                        "active_stop": _dump_dec(_position_stop(lot_state)),
                        "soft_episode_id": episode_id,
                    }
                )
                signals.append(
                    TradeSignalCandidate(
                        strategy_key=KEY,
                        strategy_version=VERSION,
                        market=market,
                        account_id=position.account_id,
                        position_id=position.position_id,
                        symbol=position.symbol,
                        action=action,  # type: ignore[arg-type]
                        suggested_target_quantity=target,
                        severity="soft",
                        reason=";".join(reasons) or "soft_exit",
                        evidence=evidence,
                        evaluated_at=now,
                        signal_key=signal_key,
                    )
                )
            # Candidate target is not a confirmed floor. Hard stop uses last_confirmed_soft_target.

        if hard_reasons:
            if last_hard_target is not None and last_hard_target <= 0:
                target = Decimal("0")
                for lot in lots:
                    remaining[lot.lot_id] = Decimal("0")
            target = sum(remaining.values(), start=Decimal("0"))
            previous_floor = last_hard_target if last_hard_target is not None else (
                last_soft_target if last_soft_target is not None else current_qty
            )
            if target < previous_floor or (last_hard_target is not None and last_hard_target <= 0 and target <= 0):
                action = _action_for(target, current_qty)
                signal_key = f"exit_v1:{position.position_id}:hard:{action}:{format(target, 'f')}"
                if signal_key != state.get("last_hard_signal_key"):
                    evidence = {
                        "rule_version": policy.rule_version,
                        "quote_status": quote_status,
                        "five_minute_status": five_status,
                        "profit_stage": _position_stage(lot_state),
                        "active_stop": _dump_dec(_position_stop(lot_state)),
                        "hard_lots": list(hard_reasons),
                    }
                    if quote is not None:
                        evidence["price"] = format(quote.price, "f")
                    evidence["hard"] = True
                    if action == "HOLD":
                        action = "EXIT"
                        target = Decimal("0")
                    signals.append(
                        TradeSignalCandidate(
                            strategy_key=KEY,
                            strategy_version=VERSION,
                            market=market,
                            account_id=position.account_id,
                            position_id=position.position_id,
                            symbol=position.symbol,
                            action=action,  # type: ignore[arg-type]
                            suggested_target_quantity=target,
                            severity="hard",
                            reason="hard_stop",
                            evidence=evidence,
                            evaluated_at=now,
                            signal_key=signal_key,
                        )
                    )
                    state["last_hard_signal_key"] = signal_key
                state["last_hard_target"] = _dump_dec(target)
                last_hard_target = target

        # Recovery clears episode in state; HOLD is not a candidate.

        if watch_now and not new_soft and not episode_active:
            watch_key = f"exit_v1:{position.position_id}:watch:{_dump_dt(last_bar_end)}"
            signals.append(
                TradeSignalCandidate(
                    strategy_key=KEY,
                    strategy_version=VERSION,
                    market=market,
                    account_id=position.account_id,
                    position_id=position.position_id,
                    symbol=position.symbol,
                    action="WATCH",
                    suggested_target_quantity=None,
                    severity="soft",
                    reason=";".join(reasons) or "普通走弱观察",
                    evidence={"five_minute_status": five_status, "quote_status": quote_status},
                    evaluated_at=now,
                    signal_key=watch_key,
                )
            )

        highs = [_dec(item.get("high_watermark")) for item in lot_state.values()]
        highs = [item for item in highs if item is not None]
        state.update(
            {
                "highest_confirmed_close": _dump_dec(max(highs) if highs else None),
                "profit_stage": _position_stage(lot_state),
                "active_stop": _dump_dec(_position_stop(lot_state)),
                "last_processed_5m_bar": _dump_dt(last_bar_end),
                "last_vwap_mode": last_vwap,
                "weak_streak": weak_streak,
                "recovery_streak": recovery_streak,
                "soft_episode_id": episode_id,
                "soft_episode_active": episode_active,
                "lots": lot_state,
                "five_minute_status": five_status,
                "quote_status": quote_status,
            }
        )
        return one_candidate(signals)


def _position_stage(lot_state: dict[str, dict[str, Any]]) -> str:
    order = {"UNKNOWN": 0, STAGE_A: 1, STAGE_B: 2, STAGE_C: 3}
    stages = [item.get("profit_stage") or "UNKNOWN" for item in lot_state.values()]
    if not stages:
        return "UNKNOWN"
    return max(stages, key=lambda item: order.get(item, 0))


def _position_stop(lot_state: dict[str, dict[str, Any]]) -> Decimal | None:
    stops = [_dec(item.get("active_stop")) for item in lot_state.values()]
    stops = [item for item in stops if item is not None]
    return max(stops) if stops else None
