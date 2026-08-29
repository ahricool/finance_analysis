"""Deterministic public-snapshot hysteresis and diversified candidate selection."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping, Sequence, Set
from typing import Any

from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, ETFRotationConfig

logger = logging.getLogger(__name__)


def _score(row: Mapping[str, Any]) -> float:
    return float(row.get("composite_score", row.get("entry_score", 0.0)) or 0.0)


def _rank(row: Mapping[str, Any]) -> int:
    return int(row.get("rank", row.get("rank_5d", 10**9)))


def _passes_gates(row: Mapping[str, Any], config: ETFRotationConfig) -> bool:
    return (
        bool(row.get("absolute_trend_eligible", True))
        and bool(row.get("liquidity_eligible", True))
        and bool(row.get("relative_strength_ready", True) or config.allow_missing_relative_strength)
        and str(row["state"]) not in config.excluded_candidate_states
    )


def select_candidates(
    rows: Sequence[Mapping[str, Any]],
    config: ETFRotationConfig = DEFAULT_CONFIG,
    *,
    previous_candidate_codes: Set[str] = frozenset(),
    regime: str = "RISK_ON",
    correlations: Mapping[tuple[str, str], float | None] | None = None,
) -> list[str]:
    """Select public strategy candidates without reading user/account state."""
    correlations = correlations or {}
    eligible: list[Mapping[str, Any]] = []
    for row in rows:
        code = str(row["code"])
        if not _passes_gates(row, config):
            continue
        if code in previous_candidate_codes:
            passes = _rank(row) <= config.hold_rank and _score(row) >= config.hold_score
        else:
            passes = regime != "RISK_OFF" and _rank(row) <= config.entry_rank and _score(row) >= config.entry_score
        if passes:
            eligible.append(row)
    eligible.sort(key=lambda row: (-_score(row), _rank(row), str(row["code"])))
    max_candidates = {
        "RISK_ON": config.max_candidates,
        "NEUTRAL": config.neutral_max_candidates,
        "RISK_OFF": config.risk_off_max_candidates,
    }.get(regime, config.neutral_max_candidates)
    if max_candidates <= 0:
        return []
    counts: Counter[str] = Counter()
    selected: list[str] = []
    for row in eligible:
        code = str(row["code"])
        risk_group = str(row.get("risk_group") or "").strip() or f"UNKNOWN:{code}"
        if risk_group.startswith("UNKNOWN:"):
            logger.warning("ETF Rotation member code=%s has no risk_group; using %s", code, risk_group)
        if counts[risk_group] >= config.max_per_risk_group:
            continue
        if any(
            correlations.get(tuple(sorted((code, existing)))) is not None
            and float(correlations[tuple(sorted((code, existing)))]) > config.max_candidate_correlation
            for existing in selected
        ):
            continue
        selected.append(code)
        counts[risk_group] += 1
        if len(selected) >= max_candidates:
            break
    return selected


def public_rotation_action(code: str, selected: Set[str], previous: Set[str]) -> str:
    if code in selected:
        return "HOLD" if code in previous else "BUY"
    if code in previous:
        return "EXIT"
    return "WATCH"


__all__ = ["public_rotation_action", "select_candidates"]
