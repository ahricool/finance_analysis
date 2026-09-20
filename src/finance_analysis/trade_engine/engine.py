# -*- coding: utf-8 -*-
"""Aggregate position strategy outputs. CORE/ADDON/Stage stay inside exit_v1."""

from __future__ import annotations

from typing import Sequence

from finance_analysis.trade_engine.models import ACTION_RANK, AggregatedSignal, TradeSignal  # pragma: allowlist secret


def aggregate_position_signals(signals: Sequence[TradeSignal]) -> AggregatedSignal:
    actionable = [item for item in signals if item.action != "WARNING"]
    if not actionable:
        warnings = tuple(item.reason for item in signals if item.action == "WARNING")
        return AggregatedSignal(action="HOLD", suggested_target_quantity=None, reasons=warnings, signals=tuple(signals))
    ranked = max(actionable, key=lambda item: ACTION_RANK.get(item.action, 0))
    targets = [
        item.suggested_target_quantity
        for item in actionable
        if item.suggested_target_quantity is not None and item.action in {"REDUCE", "EXIT"}
    ]
    target = min(targets) if targets else ranked.suggested_target_quantity
    reasons = tuple(item.reason for item in signals if item.reason)
    return AggregatedSignal(
        action=ranked.action,
        suggested_target_quantity=target,
        reasons=reasons,
        signals=tuple(signals),
    )


def should_persist(signal: TradeSignal) -> bool:
    if signal.action == "HOLD":
        return False
    if (signal.evidence or {}).get("persist") is False:
        return False
    return True
