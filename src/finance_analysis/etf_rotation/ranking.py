"""Deterministic cross-sectional ranks and trading-session rank changes."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from finance_analysis.etf_rotation.config import RETURN_WINDOWS


def rank_cross_section(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Attach ranks where 1 is strongest and percentile 100 is strongest.

    Equal returns receive the same competition rank.  Percentiles use the
    average position of the tied group, producing identical deterministic
    values for ties.  A one-member cross-section receives percentile 100.
    """
    ranked = [dict(row) for row in rows]
    total = len(ranked)
    for window in RETURN_WINDOWS:
        field = f"ret_{window}d"
        groups: dict[float, list[int]] = defaultdict(list)
        for index, row in enumerate(ranked):
            groups[float(row[field])].append(index)
        position = 1
        for value in sorted(groups, reverse=True):
            indexes = groups[value]
            rank = position
            average_position = (position + position + len(indexes) - 1) / 2.0
            percentile = 100.0 if total <= 1 else (total - average_position) / (total - 1) * 100.0
            for index in indexes:
                ranked[index][f"rank_{window}d"] = rank
                ranked[index][f"pct_rank_{window}d"] = max(0.0, min(100.0, percentile))
            position += len(indexes)
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


__all__ = ["calculate_rank_changes", "rank_cross_section"]
