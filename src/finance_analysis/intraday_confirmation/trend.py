"""Reuse Trend Preview's pure features/state/health functions, with frozen cross-section."""

from finance_analysis.trend_following.features import calculate_features
from finance_analysis.trend_following.scoring import calculate_trend_score, calculate_rs_score
from finance_analysis.trend_following.state import transition_state
from finance_analysis.trend_following.lifecycle import classify_lifecycle
from finance_analysis.trend_following.fragility import calculate_fragility
from finance_analysis.trend_following.models import DailyBar
from . import config as c


def temporary_trend(official, history, quote, benchmark_history, benchmark_quote, day, previous_day):
    result = dict(
        official_trend_state=(official or {}).get("state"),
        official_lifecycle=(official or {}).get("trend_lifecycle"),
        official_fragility=(official or {}).get("fragility_score"),
        temporary_trend_state=None,
        temporary_lifecycle=None,
        temporary_fragility=None,
        trend_score_delta=None,
        fragility_delta=None,
        impact="unavailable",
        calculation_basis="昨日横截面百分位固定；当日价格特征重算，不生成盘中排名；临时 lifecycle 不含完整衰减基线",
    )
    if not official or len(history) < c.TREND_CONFIG.minimum_history_bars or not quote or not benchmark_quote:
        return result
    if (
        history[-1].trade_date != previous_day
        or not benchmark_history
        or benchmark_history[-1].trade_date != previous_day
    ):
        return result

    # Bring the persisted forward-adjusted tail onto today's raw price scale using actual previous close.
    # No raw/adjusted splice across dividends/splits. Missing previous-close anchor => unavailable.
    def overlay(bars, q):
        if q.pre_close is None or q.pre_close <= 0 or q.volume is None:
            return None
        if any(v is None or v <= 0 for v in (q.price, q.open_price, q.high, q.low)):
            return None
        if q.low > min(q.open_price, q.price) or q.high < max(q.open_price, q.price) or q.volume < 0:
            return None
        factor = q.pre_close / bars[-1].close
        prior = [
            DailyBar(
                b.trade_date, b.open * factor, b.high * factor, b.low * factor, b.close * factor, b.volume, b.amount
            )
            for b in bars
        ]
        return prior + [DailyBar(day, q.open_price, q.high, q.low, q.price, q.volume)]

    bars = overlay(history, quote)
    bench = overlay(benchmark_history, benchmark_quote)
    if not bars or not bench or len(bench) < c.TREND_CONFIG.minimum_history_bars:
        return result
    features = calculate_features(bars, c.TREND_CONFIG.minimum_history_bars)
    if features is None:
        return result
    frozen = official.get("features") or {}
    percentile = frozen.get("weighted_slope_percentile")
    if percentile is None:
        return result
    features["weighted_slope_percentile"] = percentile
    for window in (5, 10, 20):
        features[f"rs_{window}d"] = features[f"return_{window}d"] - (bench[-1].close / bench[-window - 1].close - 1)
    features["trend_score"] = calculate_trend_score(features)[0]
    features["rs_score"] = calculate_rs_score(features)[0]
    # No new ranked candidacy. Previous formal candidates alone are evaluated here.
    features["is_candidate"] = official["state"] == "CANDIDATE"
    state = transition_state(features, official).state
    previous_duration = official.get("trend_duration_days")
    duration = (previous_duration + 1 if previous_duration is not None else None) if features["trend_candidate"] else 0
    temporary = dict(features=features, trend_duration_days=duration)
    # Rank deterioration and 3D/5D health baselines are unavailable in this narrow pool.
    # Do not fabricate a comparable official fragility delta from a different component set.
    temporary.update(calculate_fragility(temporary, {}, as_of=day))
    lifecycle = classify_lifecycle(temporary)
    delta = features["trend_score"] - official["trend_score"]
    impact = (
        "broken"
        if state == "BROKEN" or lifecycle == "BROKEN"
        else (
            "deteriorating"
            if state == "WEAKENING" or delta <= -c.TREND_SCORE_DECAY
            else "improving" if delta >= c.TREND_SCORE_DECAY else "intact"
        )
    )
    result.update(
        temporary_trend_state=state,
        temporary_lifecycle=lifecycle,
        trend_score_delta=round(delta, 2),
        impact=impact,
        fragility_unavailable_reason="未重算盘中全市场排名与完整3D/5D脆弱度基线，保持 unavailable",
    )
    return result
