"""Cross-sectional enrichment and candidate ranking."""

from __future__ import annotations

from typing import Any

from finance_analysis.trend_following.config import DEFAULT_CONFIG, TrendFollowingConfig
from finance_analysis.trend_following.features import percentile_ranks
from finance_analysis.trend_following.scoring import (
    calculate_alpha_score,
    calculate_breakout_score,
    calculate_rs_score,
    calculate_trend_score,
)


def rank_candidates(rows: list[dict[str, Any]], config: TrendFollowingConfig = DEFAULT_CONFIG) -> list[dict[str, Any]]:
    if not rows:
        return []
    for key, output in (
        ("raw_weighted_slope", "weighted_slope_percentile"),
        ("return_20d", "return_20d_percentile"),
        ("return_60d", "return_60d_percentile"),
    ):
        for row, rank in zip(rows, percentile_ranks(item[key] for item in rows)):
            row[output] = rank
    for row in rows:
        row["trend_score"], trend = calculate_trend_score(row, config)
        row["rs_score"], rs = calculate_rs_score(row, config)
        row["breakout_score"], breakout = calculate_breakout_score(row)
        row["alpha_score"], alpha = calculate_alpha_score(row, config)
        row["score_breakdown"] = {"trend": trend, "rs": rs, "breakout": breakout, "alpha": alpha}
        row["is_candidate"] = bool(
            row["trend_candidate"]
            and row["trend_score"] >= config.candidate_trend_score
            and row["rs_score"] >= config.candidate_rs_score
            and row["valid_setup"]
            and row["alpha_score"] >= config.candidate_alpha_score
        )
    rows.sort(key=lambda item: (-item["alpha_score"], str(item["code"])))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return rows


__all__ = ["rank_candidates"]
