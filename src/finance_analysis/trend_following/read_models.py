"""Read-only dashboard projections; strategy snapshots remain unchanged."""

RANKING_FIELDS = (
    "code", "rank", "state", "trend_duration_days",
    "trend_lifecycle", "fragility_score",
    "alpha_score", "trend_score", "rs_score", "breakout_score", "setup",
    "atr", "reference_price",
)
BOOLEAN_FEATURE_FIELDS = (
    "trend_candidate", "prior_compression", "compression_breakout", "trend_resume",
)
NUMERIC_FEATURE_FIELDS = (
    "alpha_version", "path_score", "setup_score", "weighted_r2",
    "positive_return_concentration", "atr_expansion_ratio",
    "downside_control_quality", "downside_upside_ratio",
    "raw_weighted_slope", "weighted_slope_percentile",
    "return_5d", "return_10d", "return_20d", "drawdown_20d",
    "rs_5d", "rs_10d", "rs_20d",
    "ma10", "ma20", "ma10_slope", "ma20_slope", "distance_from_ma20",
    "volume_ratio", "trend_quality", "trend_acceleration", "signed_efficiency_ratio_10d",
)
FEATURE_FIELDS = (*NUMERIC_FEATURE_FIELDS, *BOOLEAN_FEATURE_FIELDS)
DASHBOARD_FIELDS = (*RANKING_FIELDS, "score_breakdown")
CANDIDATE_FIELDS = ("code", "name", "rank", "state", "alpha_score")


def ranking_item(row: dict) -> dict:
    return {
        **{key: row.get(key) for key in (*RANKING_FIELDS, "name")},
        "features": {key: row.get(key) for key in FEATURE_FIELDS},
        "score_breakdown": row.get("score_breakdown") or {},
    }
