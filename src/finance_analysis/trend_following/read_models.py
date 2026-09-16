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
# Scalars from score_breakdown JSON paths. Do not load the full nested document.
SCORE_COMPONENT_PATHS = (
    ("r2_quality", ("trend", "weighted_r2")),
    ("momentum_quality", ("trend", "momentum")),
    ("return_10d_quality", ("trend", "return_10d")),
    ("return_20d_quality", ("trend", "return_20d")),
    ("drawdown_quality", ("trend", "drawdown_quality")),
    ("rs_5d_quality", ("rs", "qualities", "rs_5d")),
    ("rs_10d_quality", ("rs", "qualities", "rs_10d")),
    ("rs_20d_quality", ("rs", "qualities", "rs_20d")),
    ("breakout_quality", ("setup", "breakout_quality")),
    ("extension_quality", ("setup", "extension_quality")),
    ("volume_quality", ("setup", "volume_quality")),
    ("compression_quality", ("setup", "compression_quality")),
    ("concentration_quality", ("path", "concentration_quality")),
    ("volatility_quality", ("path", "volatility_quality")),
    ("alpha_trend_contribution", ("alpha", "contributions", "trend")),
    ("alpha_rs_contribution", ("alpha", "contributions", "rs")),
    ("alpha_setup_contribution", ("alpha", "contributions", "setup")),
    ("alpha_path_contribution", ("alpha", "contributions", "path")),
)
SCORE_COMPONENT_FIELDS = tuple(name for name, _path in SCORE_COMPONENT_PATHS)
FEATURE_FIELDS = (*NUMERIC_FEATURE_FIELDS, *BOOLEAN_FEATURE_FIELDS, *SCORE_COMPONENT_FIELDS)
DASHBOARD_FIELDS = RANKING_FIELDS
CANDIDATE_FIELDS = ("code", "name", "rank", "state", "alpha_score")


def score_component_expression(json_column, path: tuple[str, ...]):
    expression = json_column
    for key in path:
        expression = expression[key]
    return expression.as_float()


def ranking_item(row: dict) -> dict:
    return {
        **{key: row.get(key) for key in (*RANKING_FIELDS, "name")},
        "features": {key: row.get(key) for key in FEATURE_FIELDS},
    }
