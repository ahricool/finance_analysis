"""Deterministic, risk-group-aware buy candidate selection."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from finance_analysis.etf_rotation.config import DEFAULT_CONFIG, ETFRotationConfig

logger = logging.getLogger(__name__)


def select_candidates(
    rows: Sequence[Mapping[str, Any]],
    config: ETFRotationConfig = DEFAULT_CONFIG,
) -> list[str]:
    eligible = [row for row in rows if str(row["state"]) not in config.excluded_candidate_states]
    eligible.sort(
        key=lambda row: (
            -float(row["entry_score"]),
            -float(row["momentum_score"]),
            int(row["rank_5d"]),
            str(row["code"]),
        )
    )
    counts: Counter[str] = Counter()
    selected: list[str] = []
    for row in eligible:
        code = str(row["code"])
        risk_group = str(row.get("risk_group") or "").strip()
        if not risk_group:
            risk_group = f"UNKNOWN:{code}"
            logger.warning("ETF Rotation member code=%s has no risk_group; using %s", code, risk_group)
        if counts[risk_group] >= config.max_per_risk_group:
            continue
        selected.append(code)
        counts[risk_group] += 1
        if len(selected) >= config.max_candidates:
            break
    return selected


__all__ = ["select_candidates"]
