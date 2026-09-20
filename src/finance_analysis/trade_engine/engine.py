# -*- coding: utf-8 -*-
"""Aggregate candidates. CORE/ADDON/Stage stay inside exit_v1."""

from __future__ import annotations

from typing import Sequence

from .models import ACTION_RANK, AggregatedSignal, TradeSignalCandidate  # pragma: allowlist secret


def aggregate_position_signals(candidates: Sequence[TradeSignalCandidate]) -> AggregatedSignal:
    if not candidates:
        return AggregatedSignal(action="HOLD", suggested_target_quantity=None, reasons=(), candidates=())
    ranked = max(candidates, key=lambda item: ACTION_RANK.get(item.action, 0))
    targets = [
        item.suggested_target_quantity
        for item in candidates
        if item.suggested_target_quantity is not None and item.action in {"REDUCE", "EXIT"}
    ]
    target = min(targets) if targets else ranked.suggested_target_quantity
    return AggregatedSignal(
        action=ranked.action,
        suggested_target_quantity=target,
        reasons=tuple(item.reason for item in candidates if item.reason),
        candidates=tuple(candidates),
    )
