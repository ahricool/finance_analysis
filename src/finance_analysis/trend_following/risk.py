"""Deterministic risk sizing using existing snapshot inputs, in decimal units."""

from __future__ import annotations

import math
from typing import Literal, TypedDict

from .config import DEFAULT_CONFIG, TrendFollowingConfig


class TrendRiskSizing(TypedDict):
    risk_budget_pct: float
    max_position_pct: float
    atr_multiple: float
    atr_stop_pct: float
    structure_stop_pct: float
    stop_loss_pct: float
    stop_price: float
    suggested_position_pct: float
    stop_basis: Literal["ATR", "STRUCTURE"]


def calculate_risk_sizing(
    reference_price: float | None,
    atr: float | None,
    previous_low_10: float | None,
    config: TrendFollowingConfig = DEFAULT_CONFIG,
) -> TrendRiskSizing | None:
    """Size planned account risk independently of Entry, State and Alpha.

    Missing/invalid structure contributes zero distance. Invalid required inputs
    or unrepresentable arithmetic produce no advice, never NaN/Infinity.
    """
    required = (reference_price, atr, config.risk_budget_pct,
                config.risk_stop_atr_multiple, config.risk_max_position_pct)
    if any(value is None or not math.isfinite(value) or value <= 0 for value in required):
        return None
    atr_stop_pct = config.risk_stop_atr_multiple * (atr / reference_price)
    structure_stop_pct = 0.0
    if previous_low_10 is not None and math.isfinite(previous_low_10) and 0 < previous_low_10 < reference_price:
        structure_stop_pct = (reference_price - previous_low_10) / reference_price
    stop_loss_pct = max(atr_stop_pct, structure_stop_pct)
    if not math.isfinite(stop_loss_pct) or stop_loss_pct <= 0 or stop_loss_pct >= 1:
        return None
    return TrendRiskSizing(
        risk_budget_pct=config.risk_budget_pct,
        max_position_pct=config.risk_max_position_pct,
        atr_multiple=config.risk_stop_atr_multiple,
        atr_stop_pct=atr_stop_pct,
        structure_stop_pct=structure_stop_pct,
        stop_loss_pct=stop_loss_pct,
        stop_price=reference_price * max(0.0, 1 - stop_loss_pct),
        suggested_position_pct=min(config.risk_budget_pct / stop_loss_pct, config.risk_max_position_pct),
        stop_basis="STRUCTURE" if structure_stop_pct > atr_stop_pct else "ATR",
    )
