"""Deterministic public-snapshot hysteresis and diversified candidate selection."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping, Sequence, Set
from typing import Any

from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, ETFRotationConfig

logger = logging.getLogger(__name__)


def _composite_score(row: Mapping[str, Any]) -> float:
    return float(row.get("composite_score", row.get("entry_score", 0.0)) or 0.0)


def _entry_score(row: Mapping[str, Any]) -> float:
    return float(row.get("entry_score", 0.0) or 0.0)


def _rank(row: Mapping[str, Any]) -> int:
    return int(row.get("rank", row.get("rank_5d", 10**9)))


def _passes_hard_gates(row: Mapping[str, Any], config: ETFRotationConfig) -> bool:
    return (
        bool(row.get("absolute_trend_eligible", True))
        and bool(row.get("liquidity_eligible", True))
        and bool(row.get("relative_strength_ready", True) or config.allow_missing_relative_strength)
    )


def _passes_entry_gates(row: Mapping[str, Any], config: ETFRotationConfig) -> bool:
    return _passes_hard_gates(row, config) and str(row["state"]) not in config.excluded_candidate_states


def _sort_key(row: Mapping[str, Any]) -> tuple[float, int, str]:
    return (-_composite_score(row), _rank(row), str(row["code"]))


def _candidate_limit(regime: str, config: ETFRotationConfig) -> int:
    return {
        "RISK_ON": config.max_candidates,
        "NEUTRAL": config.neutral_max_candidates,
        "RISK_OFF": config.risk_off_max_candidates,
    }.get(regime, config.neutral_max_candidates)


def _risk_group(row: Mapping[str, Any]) -> str:
    code = str(row["code"])
    return str(row.get("risk_group") or "").strip() or f"UNKNOWN:{code}"


def select_candidates(
    rows: Sequence[Mapping[str, Any]],
    config: ETFRotationConfig = DEFAULT_CONFIG,
    *,
    previous_candidate_codes: Set[str] = frozenset(),
    regime: str = "RISK_ON",
    correlations: Mapping[tuple[str, str], float | None] | None = None,
    diagnostics: list[str] | None = None,
) -> list[str]:
    """Keep valid public holds first, then fill remaining slots with new entries."""
    correlations = correlations or {}
    hold_limit = config.max_candidates
    entry_capacity = _candidate_limit(regime, config)
    if hold_limit <= 0:
        return []

    held = sorted(
        (
            row
            for row in rows
            if str(row["code"]) in previous_candidate_codes
            and _passes_hard_gates(row, config)
            and _rank(row) <= config.hold_rank_threshold
            and _composite_score(row) >= config.hold_composite_threshold
        ),
        key=_sort_key,
    )
    if len(held) > hold_limit:
        warning = (
            f"valid holds exceed candidate limit: holds={len(held)} limit={hold_limit}; "
            "truncated by composite, rank, and code"
        )
        logger.warning(
            "ETF Rotation %s",
            warning,
        )
        if diagnostics is not None:
            diagnostics.append(warning)
        held = held[:hold_limit]

    selected = [str(row["code"]) for row in held]
    counts: Counter[str] = Counter(_risk_group(row) for row in held)
    entries = sorted(
        (
            row
            for row in rows
            if str(row["code"]) not in previous_candidate_codes
            and regime != "RISK_OFF"
            and _passes_entry_gates(row, config)
            and _rank(row) <= config.entry_rank_threshold
            and _entry_score(row) >= config.entry_score_threshold
        ),
        key=_sort_key,
    )
    for row in entries:
        if len(selected) >= entry_capacity:
            break
        code = str(row["code"])
        risk_group = _risk_group(row)
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
    return selected


def public_rotation_action(
    row: Mapping[str, Any],
    selected: Set[str],
    previous: Set[str],
    config: ETFRotationConfig = DEFAULT_CONFIG,
) -> str | None:
    code = str(row["code"])
    if code in selected:
        return "HOLD" if code in previous else "BUY"
    if code in previous:
        return "EXIT"
    if (
        _passes_hard_gates(row, config)
        and str(row["state"]) != "WEAK"
        and _composite_score(row) >= config.watch_composite_threshold
    ):
        return "WATCH"
    return None


__all__ = ["public_rotation_action", "select_candidates"]
