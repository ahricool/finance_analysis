"""Read-only dashboard projections; strategy snapshots remain unchanged."""

RANKING_FIELDS = (
    "code", "rank", "state", "action", "pending_action", "trend_duration_days",
    "trend_lifecycle", "fragility_score",
    "alpha_score", "trend_score", "rs_score", "breakout_score", "setup",
    "atr", "reference_price", "signal_date", "signal_price", "opened_at", "entry_price",
    "initial_stop", "next_add_price", "exit_level", "suggested_initial_weight",
)
FEATURE_FIELDS = ("return_5d", "return_10d", "return_20d", "volume_ratio", "distance_from_ma20")
DASHBOARD_FIELDS = (*RANKING_FIELDS, "units", "suggested_max_weight", "trailing_stop")
CANDIDATE_FIELDS = ("code", "name", "rank", "state", "action", "alpha_score")


def ranking_item(row: dict) -> dict:
    return {
        **{key: row.get(key) for key in (*RANKING_FIELDS, "name")},
        "features": {key: row.get(key) for key in FEATURE_FIELDS},
    }
