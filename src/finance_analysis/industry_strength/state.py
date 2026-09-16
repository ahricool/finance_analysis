"""Ordered, explanatory market states; no LLM or execution state."""

import math
from .config import DEFAULT_CONFIG


def classify(row, industry_count, previous=None, config=DEFAULT_CONFIG):
    score = row["strength_score"]
    gain = row["rank_change_3d"]
    if score >= config.cooling_score and (
        row["momentum_acceleration_5d"] < 0
        or (row["up_ratio"] is not None and row["up_ratio"] < config.cooling_breadth)
        or (gain is not None and gain <= config.cooling_rank_loss)
    ):
        return "COOLING"
    if (
        gain is not None
        and gain >= config.emerging_rank_gain
        and row["rs_5d"] > 0
        and row["momentum_acceleration_5d"] > 0
        and row["acceleration_percentile"] >= config.emerging_acceleration_percentile
        and row["turnover_ratio_5d"] >= config.emerging_turnover
    ):
        return "EMERGING"
    if (
        score >= config.strong_score
        and row["strength_rank"] <= math.ceil(industry_count * config.strong_top_fraction)
        and previous is not None
        and previous["strength_score"] >= config.strong_score
        and row["rs_5d"] > 0
        and row["rs_10d"] > 0
        and row["rs_20d"] > 0
        and (row["up_ratio"] is None or row["up_ratio"] >= config.strong_breadth)
        and (row["above_ma20_ratio"] is None or row["above_ma20_ratio"] >= config.strong_ma20)
    ):
        return "STRONG"
    if (
        score <= config.weak_score
        and row["rs_5d"] < 0
        and row["rs_10d"] < 0
        and (row["up_ratio"] is None or row["up_ratio"] <= config.weak_breadth)
        and (row["above_ma20_ratio"] is None or row["above_ma20_ratio"] <= config.weak_ma20)
    ):
        return "WEAK"
    return "NEUTRAL"
