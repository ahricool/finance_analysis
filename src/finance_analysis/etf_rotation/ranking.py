"""Deterministic cross-sectional ranks and trading-session rank changes."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any
import math

from finance_analysis.etf_rotation.config import RETURN_WINDOWS

FACTOR_RANK_DIRECTIONS = {
    "trend_quality_25d": True,
    "efficiency_ratio_20d": True,
    "rs_20d": True,
    "rs_60d": True,
    "trend_acceleration": True,
    "momentum_acceleration": True,
    "risk_adjusted_momentum_60d": True,
    "max_drawdown_60d": True,
}


def rank_feature(
    rows: Sequence[Mapping[str, Any]], field: str, *, highest_is_best: bool = True
) -> list[dict[str, Any]]:
    """Rank one finite feature; invalid/missing values remain explicitly unranked."""
    ranked = [dict(row) for row in rows]
    groups: dict[float, list[int]] = defaultdict(list)
    for index, row in enumerate(ranked):
        value = row.get(field)
        if value is None:
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            groups[parsed].append(index)
    total = sum(len(indexes) for indexes in groups.values())
    position = 1
    for value in sorted(groups, reverse=highest_is_best):
        indexes = groups[value]
        average_position = position + (len(indexes) - 1) / 2.0
        percentile = 100.0 if total <= 1 else (total - average_position) / (total - 1) * 100.0
        for index in indexes:
            ranked[index][f"rank_{field}"] = position
            ranked[index][f"pct_rank_{field}"] = max(0.0, min(100.0, percentile))
        position += len(indexes)
    for row in ranked:
        row.setdefault(f"rank_{field}", None)
        row.setdefault(f"pct_rank_{field}", None)
    return ranked


def rank_features(
    rows: Sequence[Mapping[str, Any]], directions: Mapping[str, bool]
) -> list[dict[str, Any]]:
    ranked = [dict(row) for row in rows]
    for field, highest_is_best in directions.items():
        ranked = rank_feature(ranked, field, highest_is_best=highest_is_best)
    return ranked


def rank_cross_section(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Attach ranks where 1 is strongest and percentile 100 is strongest.

    Equal returns receive the same competition rank.  Percentiles use the
    average position of the tied group, producing identical deterministic
    values for ties.  A one-member cross-section receives percentile 100.
    """
    ranked = rank_features([dict(row) for row in rows], {f"ret_{window}d": True for window in RETURN_WINDOWS})
    for row in ranked:
        for window in RETURN_WINDOWS:
            row[f"rank_{window}d"] = row.pop(f"rank_ret_{window}d")
            row[f"pct_rank_{window}d"] = row.pop(f"pct_rank_ret_{window}d")
    return ranked


def calculate_rank_changes(
    current_rank: int,
    historical_ranks: Mapping[int, int | None],
) -> dict[str, int | None]:
    """Return historical rank minus current rank for 1/3/5 snapshot offsets."""
    return {
        f"rank_change_{offset}d": (
            None if historical_ranks.get(offset) is None else int(historical_ranks[offset]) - int(current_rank)
        )
        for offset in (1, 3, 5)
    }


__all__ = [
    "FACTOR_RANK_DIRECTIONS",
    "calculate_rank_changes",
    "rank_cross_section",
    "rank_feature",
    "rank_features",
]
