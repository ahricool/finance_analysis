# -*- coding: utf-8 -*-
"""Deterministic rule engine that turns intraday metrics into signal candidates.

Each rule is a callable ``(metrics, phase) -> bool`` paired with a signal type
(:class:`SignalRule`). Thresholds vary by intraday phase (opening / morning /
afternoon / closing) because A-share noise differs across the session. The LLM
only ever reviews candidates these rules emit — it never scans the market.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from finance_analysis.integrations.market_data.realtime_types import safe_float

Metrics = Dict[str, Any]
RulePredicate = Callable[[Metrics, str], bool]

# Signal classification used by notifications and the LLM-down fallback path.
SIGNAL_CATEGORY: Dict[str, str] = {
    "near_limit_up_acceleration": "opportunity",
    "limit_up_sealed": "info",
    "limit_up_break_open": "risk",
    "strong_to_weak_failure": "risk",
    "weak_to_strong_reversal": "opportunity",
    "high_open_low_move": "risk",
    "abnormal_volume_breakout": "opportunity",
    "near_limit_down_risk": "risk",
    "one_word_limit_up": "info",
}

# Base severity per signal; risk escalation can override at runtime.
SIGNAL_SEVERITY: Dict[str, str] = {
    "near_limit_up_acceleration": "info",
    "limit_up_sealed": "info",
    "limit_up_break_open": "warning",
    "strong_to_weak_failure": "warning",
    "weak_to_strong_reversal": "info",
    "high_open_low_move": "warning",
    "abnormal_volume_breakout": "info",
    "near_limit_down_risk": "warning",
    "one_word_limit_up": "info",
}

# Risk-class signals that may still alert (downgraded) when the LLM is offline.
FALLBACK_RISK_SIGNALS = {
    "limit_up_break_open",
    "strong_to_weak_failure",
    "near_limit_down_risk",
}


@dataclass
class PhaseThresholds:
    """Phase-dependent thresholds shared across rules."""

    breakout_change_5m: float
    breakout_change_15m: float
    breakout_volume_ratio: float
    breakout_relative_15m: float
    near_limit_up_distance: float
    weakness_change_5m: float
    drawdown_from_high: float
    rebound_from_low: float
    allow_opportunity: bool


_PHASE_THRESHOLDS: Dict[str, PhaseThresholds] = {
    "opening": PhaseThresholds(
        breakout_change_5m=1.2,
        breakout_change_15m=2.5,
        breakout_volume_ratio=2.5,
        breakout_relative_15m=1.2,
        near_limit_up_distance=2.0,
        weakness_change_5m=-1.0,
        drawdown_from_high=2.0,
        rebound_from_low=1.5,
        allow_opportunity=False,
    ),
    "morning": PhaseThresholds(
        breakout_change_5m=0.8,
        breakout_change_15m=1.5,
        breakout_volume_ratio=2.0,
        breakout_relative_15m=0.8,
        near_limit_up_distance=2.5,
        weakness_change_5m=-0.8,
        drawdown_from_high=1.8,
        rebound_from_low=1.2,
        allow_opportunity=True,
    ),
    "afternoon": PhaseThresholds(
        breakout_change_5m=0.8,
        breakout_change_15m=1.5,
        breakout_volume_ratio=2.0,
        breakout_relative_15m=0.8,
        near_limit_up_distance=2.5,
        weakness_change_5m=-0.8,
        drawdown_from_high=1.8,
        rebound_from_low=1.2,
        allow_opportunity=True,
    ),
    "closing": PhaseThresholds(
        breakout_change_5m=1.0,
        breakout_change_15m=1.8,
        breakout_volume_ratio=2.2,
        breakout_relative_15m=1.0,
        near_limit_up_distance=2.0,
        weakness_change_5m=-0.6,
        drawdown_from_high=1.5,
        rebound_from_low=1.0,
        allow_opportunity=True,
    ),
}


def thresholds_for_phase(phase: str) -> PhaseThresholds:
    return _PHASE_THRESHOLDS.get(phase, _PHASE_THRESHOLDS["morning"])


@dataclass
class SignalRule:
    """Pair a signal type with the predicate that decides whether it fires."""

    signal_type: str
    matches: RulePredicate

    def __call__(self, metrics: Metrics, phase: str) -> bool:
        return self.matches(metrics, phase)


def evaluate_signal_candidates(
    metrics: Metrics,
    phase: str = "morning",
    rules: Optional[Sequence[SignalRule]] = None,
) -> List[Dict[str, Any]]:
    """Run each rule against ``metrics`` and return the matching candidates."""
    active_rules = DEFAULT_A_SHARE_INTRADAY_SIGNAL_RULES if rules is None else rules
    candidates: List[Dict[str, Any]] = []
    for rule in active_rules:
        try:
            fired = rule(metrics, phase)
        except Exception:
            fired = False
        if fired:
            candidates.append({"signal_type": rule.signal_type})
    return candidates


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------

def _has_limit(metrics: Metrics) -> bool:
    return bool(metrics.get("has_price_limit")) and metrics.get("limit_up_price")


def near_limit_up_acceleration(metrics: Metrics, phase: str) -> bool:
    if not _has_limit(metrics) or metrics.get("one_word_limit_up"):
        return False
    if metrics.get("is_limit_up"):
        return False  # already sealed -> handled by limit_up_sealed
    t = thresholds_for_phase(phase)
    return (
        _lte(metrics.get("distance_to_limit_up_pct"), t.near_limit_up_distance)
        and _gt(metrics.get("distance_to_limit_up_pct"), 0)
        and _gte(metrics.get("change_5m"), t.breakout_change_5m)
        and _gte(metrics.get("change_15m"), 0)
        and _gte(metrics.get("intraday_volume_ratio"), t.breakout_volume_ratio * 0.6)
        and bool(metrics.get("price_above_vwap"))
    )


def limit_up_sealed(metrics: Metrics, phase: str) -> bool:
    return bool(_has_limit(metrics) and metrics.get("is_limit_up"))


def limit_up_break_open(metrics: Metrics, phase: str) -> bool:
    if not _has_limit(metrics):
        return False
    t = thresholds_for_phase(phase)
    return (
        bool(metrics.get("opened_from_limit_up"))
        and not metrics.get("is_limit_up")
        and _gte(metrics.get("drawdown_from_high_pct"), t.drawdown_from_high)
    )


def strong_to_weak_failure(metrics: Metrics, phase: str) -> bool:
    t = thresholds_for_phase(phase)
    early_strong = _gte(metrics.get("relative_to_main_index_15m"), 0.5) or _gte(
        metrics.get("change_30m"), 1.0
    )
    return (
        early_strong
        and bool(metrics.get("price_below_vwap"))
        and _lte(metrics.get("change_5m"), t.weakness_change_5m)
        and _gte(metrics.get("drawdown_from_high_pct"), t.drawdown_from_high)
    )


def weak_to_strong_reversal(metrics: Metrics, phase: str) -> bool:
    t = thresholds_for_phase(phase)
    if not t.allow_opportunity:
        return False
    return (
        bool(metrics.get("crossed_above_vwap"))
        and _gte(metrics.get("change_15m"), 1.0)
        and _gte(metrics.get("rebound_from_low_pct"), t.rebound_from_low)
        and _gte(metrics.get("intraday_volume_ratio"), t.breakout_volume_ratio * 0.7)
        and not _lte(metrics.get("relative_to_sector_15m"), -1.5)
    )


def high_open_low_move(metrics: Metrics, phase: str) -> bool:
    t = thresholds_for_phase(phase)
    return (
        _gte(metrics.get("opening_gap_pct"), 1.5)
        and bool(metrics.get("price_below_vwap"))
        and _gte(metrics.get("drawdown_from_high_pct"), t.drawdown_from_high)
        and _lte(metrics.get("change_15m"), 0)
    )


def abnormal_volume_breakout(metrics: Metrics, phase: str) -> bool:
    t = thresholds_for_phase(phase)
    if not t.allow_opportunity:
        return False
    return (
        _gte(metrics.get("intraday_volume_ratio"), t.breakout_volume_ratio)
        and _gte(metrics.get("change_5m"), t.breakout_change_5m)
        and _gte(metrics.get("change_15m"), t.breakout_change_15m)
        and bool(metrics.get("price_above_vwap"))
        and _gte(metrics.get("relative_to_main_index_15m"), t.breakout_relative_15m)
    )


def near_limit_down_risk(metrics: Metrics, phase: str) -> bool:
    if not (metrics.get("has_price_limit") and metrics.get("limit_down_price")):
        return False
    t = thresholds_for_phase(phase)
    return (
        _lte(metrics.get("distance_to_limit_down_pct"), t.near_limit_up_distance)
        and _lte(metrics.get("change_5m"), t.weakness_change_5m)
        and bool(metrics.get("price_below_vwap"))
    )


# Default rule set: edit, reorder, add or drop entries here to tune behaviour.
DEFAULT_A_SHARE_INTRADAY_SIGNAL_RULES: List[SignalRule] = [
    SignalRule("limit_up_break_open", limit_up_break_open),
    SignalRule("near_limit_down_risk", near_limit_down_risk),
    SignalRule("strong_to_weak_failure", strong_to_weak_failure),
    SignalRule("high_open_low_move", high_open_low_move),
    SignalRule("near_limit_up_acceleration", near_limit_up_acceleration),
    SignalRule("limit_up_sealed", limit_up_sealed),
    SignalRule("abnormal_volume_breakout", abnormal_volume_breakout),
    SignalRule("weak_to_strong_reversal", weak_to_strong_reversal),
]


def _gte(value: Any, threshold: float) -> bool:
    parsed = safe_float(value)
    return bool(parsed is not None and parsed >= threshold)


def _gt(value: Any, threshold: float) -> bool:
    parsed = safe_float(value)
    return bool(parsed is not None and parsed > threshold)


def _lte(value: Any, threshold: float) -> bool:
    parsed = safe_float(value)
    return bool(parsed is not None and parsed <= threshold)
