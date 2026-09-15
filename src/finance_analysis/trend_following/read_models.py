"""Read-only dashboard projections; strategy snapshots remain unchanged."""

RANKING_FIELDS = (
    "code", "rank", "state", "trend_duration_days",
    "trend_lifecycle", "fragility_score",
    "alpha_score", "trend_score", "rs_score", "breakout_score", "setup",
    "atr", "reference_price",
)
FEATURE_FIELDS = ("return_5d", "return_10d", "return_20d", "volume_ratio", "distance_from_ma20")
DASHBOARD_FIELDS = RANKING_FIELDS
CANDIDATE_FIELDS = ("code", "name", "rank", "state", "alpha_score")


def ranking_item(row: dict) -> dict:
    return {
        **{key: row.get(key) for key in (*RANKING_FIELDS, "name")},
        "features": {key: row.get(key) for key in FEATURE_FIELDS},
    }
