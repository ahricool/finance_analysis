# -*- coding: utf-8 -*-
"""Rule-based evaluation that turns a metric snapshot into signal candidates."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from data_provider.realtime_types import safe_float

from .config import DEFAULT_INTRADAY_SIGNAL_RULES


def evaluate_signal_candidates(
    metrics: Dict[str, Any],
    rules: Optional[Dict[str, Dict[str, float]]] = None,
) -> List[Dict[str, Any]]:
    """Evaluate decoupled threshold rules and return matching candidate signals."""
    cfg = rules or DEFAULT_INTRADAY_SIGNAL_RULES
    candidates: List[Dict[str, Any]] = []

    if _is_relative_strength_breakout(metrics, cfg["relative_strength_breakout"]):
        candidates.append({"signal_type": "relative_strength_breakout", "rule": cfg["relative_strength_breakout"]})

    if _is_weak_to_strong_reversal(metrics, cfg["weak_to_strong_reversal"]):
        candidates.append({"signal_type": "weak_to_strong_reversal", "rule": cfg["weak_to_strong_reversal"]})

    if _is_relative_strength_failure(metrics, cfg["relative_strength_failure"]):
        candidates.append({"signal_type": "relative_strength_failure", "rule": cfg["relative_strength_failure"]})

    return candidates


def _is_relative_strength_breakout(metrics: Dict[str, Any], rule: Dict[str, float]) -> bool:
    return (
        _gte(metrics.get("change_5m"), rule["change_5m_min"])
        and _gte(metrics.get("change_15m"), rule["change_15m_min"])
        and _gte(metrics.get("relative_to_qqq_15m"), rule["relative_to_qqq_15m_min"])
        and _gte(metrics.get("volume_ratio_5m"), rule["volume_ratio_5m_min"])
        and bool(metrics.get("price_above_vwap"))
        and (
            bool(metrics.get("near_intraday_high"))
            or _lte(metrics.get("high_distance_pct"), rule["near_high_pct"])
        )
    )


def _is_weak_to_strong_reversal(metrics: Dict[str, Any], rule: Dict[str, float]) -> bool:
    return (
        _lte(metrics.get("early_relative_to_qqq"), rule["early_relative_to_qqq_max"])
        and _gte(metrics.get("relative_to_qqq_15m"), rule["relative_to_qqq_15m_min"])
        and bool(metrics.get("crossed_above_vwap"))
        and _gte(metrics.get("change_15m"), rule["change_15m_min"])
        and _gte(metrics.get("volume_ratio_5m"), rule["volume_ratio_5m_min"])
    )


def _is_relative_strength_failure(metrics: Dict[str, Any], rule: Dict[str, float]) -> bool:
    return (
        _gte(metrics.get("early_relative_to_qqq"), rule["early_relative_to_qqq_min"])
        and _lte(metrics.get("relative_to_qqq_15m"), rule["relative_to_qqq_15m_max"])
        and bool(metrics.get("price_below_vwap"))
        and _lte(metrics.get("change_5m"), rule["change_5m_max"])
        and _gte(metrics.get("volume_ratio_5m"), rule["volume_ratio_5m_min"])
    )


def _gte(value: Any, threshold: float) -> bool:
    parsed = safe_float(value)
    return bool(parsed is not None and parsed >= threshold)


def _lte(value: Any, threshold: float) -> bool:
    parsed = safe_float(value)
    return bool(parsed is not None and parsed <= threshold)
