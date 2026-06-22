# -*- coding: utf-8 -*-
"""Rule-based evaluation that turns a metric snapshot into signal candidates.

A "rule" here is simply a callable ``(metrics) -> bool`` paired with a signal
type (:class:`SignalRule`). ``evaluate_signal_candidates`` just iterates over the
rules and calls each one against the metrics, so adding, removing or tweaking a
condition only means editing the matching function below — no dict with a fixed
set of keys to keep in sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from finance_analysis.integrations.market_data.realtime_types import safe_float

Metrics = Dict[str, Any]
RulePredicate = Callable[[Metrics], bool]


@dataclass
class SignalRule:
    """Pair a signal type with the predicate that decides whether it fires."""

    signal_type: str
    matches: RulePredicate

    def __call__(self, metrics: Metrics) -> bool:
        return self.matches(metrics)


def evaluate_signal_candidates(
    metrics: Metrics,
    rules: Optional[Sequence[RulePredicate]] = None,
) -> List[Dict[str, Any]]:
    """Run each rule against ``metrics`` and return the matching candidates.

    ``rules`` is any sequence of callables. :class:`SignalRule` instances carry
    their own ``signal_type``; plain callables fall back to their function name.
    """
    active_rules = DEFAULT_INTRADAY_SIGNAL_RULES if rules is None else rules
    candidates: List[Dict[str, Any]] = []

    for rule in active_rules:
        if rule(metrics):
            candidates.append({"signal_type": _signal_type_of(rule), "rule": rule})

    return candidates


def _signal_type_of(rule: RulePredicate) -> str:
    signal_type = getattr(rule, "signal_type", None)
    if signal_type:
        return str(signal_type)
    return getattr(rule, "__name__", "custom_signal")


def is_relative_strength_breakout(
    metrics: Metrics,
    *,
    change_5m_min: float = 0.8,
    change_15m_min: float = 1.5,
    relative_to_qqq_15m_min: float = 0.8,
    volume_ratio_5m_min: float = 2.0,
    near_high_pct: float = 0.25,
) -> bool:
    return (
        _gte(metrics.get("change_5m"), change_5m_min)
        and _gte(metrics.get("change_15m"), change_15m_min)
        and _gte(metrics.get("relative_to_qqq_15m"), relative_to_qqq_15m_min)
        and _gte(metrics.get("volume_ratio_5m"), volume_ratio_5m_min)
        and bool(metrics.get("price_above_vwap"))
        and (
            bool(metrics.get("near_intraday_high"))
            or _lte(metrics.get("high_distance_pct"), near_high_pct)
        )
    )


def is_weak_to_strong_reversal(
    metrics: Metrics,
    *,
    early_relative_to_qqq_max: float = -0.3,
    relative_to_qqq_15m_min: float = 0.3,
    change_15m_min: float = 1.0,
    volume_ratio_5m_min: float = 1.8,
) -> bool:
    return (
        _lte(metrics.get("early_relative_to_qqq"), early_relative_to_qqq_max)
        and _gte(metrics.get("relative_to_qqq_15m"), relative_to_qqq_15m_min)
        and bool(metrics.get("crossed_above_vwap"))
        and _gte(metrics.get("change_15m"), change_15m_min)
        and _gte(metrics.get("volume_ratio_5m"), volume_ratio_5m_min)
    )


def is_relative_strength_failure(
    metrics: Metrics,
    *,
    early_relative_to_qqq_min: float = 0.5,
    relative_to_qqq_15m_max: float = -0.3,
    change_5m_max: float = -0.8,
    volume_ratio_5m_min: float = 2.0,
) -> bool:
    return (
        _gte(metrics.get("early_relative_to_qqq"), early_relative_to_qqq_min)
        and _lte(metrics.get("relative_to_qqq_15m"), relative_to_qqq_15m_max)
        and bool(metrics.get("price_below_vwap"))
        and _lte(metrics.get("change_5m"), change_5m_max)
        and _gte(metrics.get("volume_ratio_5m"), volume_ratio_5m_min)
    )


# Default rule set: edit, reorder, add or drop entries here to tune behavior.
DEFAULT_INTRADAY_SIGNAL_RULES: List[SignalRule] = [
    SignalRule("relative_strength_breakout", is_relative_strength_breakout),
    SignalRule("weak_to_strong_reversal", is_weak_to_strong_reversal),
    SignalRule("relative_strength_failure", is_relative_strength_failure),
]


def _gte(value: Any, threshold: float) -> bool:
    parsed = safe_float(value)
    return bool(parsed is not None and parsed >= threshold)


def _lte(value: Any, threshold: float) -> bool:
    parsed = safe_float(value)
    return bool(parsed is not None and parsed <= threshold)
