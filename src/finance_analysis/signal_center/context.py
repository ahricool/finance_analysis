"""Small source-native context; persist exactly the evidence used by synthesis."""

TREND_FIELDS = (
    "id rank previous_rank previous_state previous_trade_date previous_population rank_change state setup "
    "alpha_score trend_score rs_score breakout_score trend_lifecycle trend_duration_days "
    "fragility_score reference_price trade_date generated_at"
)
FEATURE_FIELDS = (
    "return_3d return_5d return_10d return_20d rs_5d rs_10d rs_20d distance_from_ma20 "
    "breakout_distance volume_ratio trend_acceleration trend_quality distance_from_recent_high "
    "drawdown_20d ma10 ma20 previous_high_20 recent_structure_low"
)
INDUSTRY_FIELDS = (
    "id industry_code industry_name trend_rank strength_rank strength_score state rank_change_1d rank_change_3d "
    "rank_change_5d momentum_acceleration_5d rs_5d rs_10d trade_date generated_at members_observed_at"
)


def project(row, fields):
    return {k: row.get(k) for k in fields.split()}


def candidate_context(candidate):
    result = dict(candidate)
    trend = candidate.get("trend")
    if trend:
        result["trend"] = dict(
            project(trend, TREND_FIELDS), features=project(trend.get("features") or {}, FEATURE_FIELDS)
        )
    result["industry"] = [project(row, INDUSTRY_FIELDS) for row in candidate.get("industry", [])]
    return result
