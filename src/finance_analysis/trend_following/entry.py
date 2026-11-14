"""Independent Entry quality and confirmation; never changes Alpha or trend state."""

from .config import DEFAULT_CONFIG, TrendFollowingConfig
from .entry_setups import ENTRY_KINDS, entry_context
from .scoring import clamp, gaussian, tanh_quality


def calculate_entry(row: dict, config: TrendFollowingConfig = DEFAULT_CONFIG, *, bars=None, sessions=None) -> dict:
    context = entry_context(bars, config, sessions=sessions) if bars is not None else row.get("entry_context", {})
    setup = row["score_breakdown"]["setup"]
    fragility = row.get("fragility_score")
    clv = row.get("close_location_value")
    atr = context.get("atr") or row.get("atr20") or row.get("atr")
    breakout = any(row.get(key, False) for key in ("breakout_10d", "breakout_20d", "compression_breakout"))
    level = row.get("previous_high_20" if row.get("breakout_20d") else "previous_high_10")
    distance = (row["reference_price"] - level) / atr if level is not None and atr and atr > 0 else None
    checks = {
        "rs_score": row["rs_score"] >= config.entry_rs_min,
        "alpha_score": row["alpha_score"] >= config.entry_alpha_min,
        "path_score": row["path_score"] >= config.entry_path_min,
        "ma20_rising": row["ma20_slope"] > 0,
        "rs10_positive": row["rs_10d"] > 0,
        "fragility": fragility is None or fragility < config.entry_fragility_max,
        "breakout": breakout,
        "trend_score": row["trend_score"] >= config.entry_trend_min,
        "extension": distance is not None
        and config.entry_breakout_min_atr <= distance <= config.entry_breakout_max_atr,
        "clv": clv is not None and clv >= config.entry_clv_min,
    }
    shared = {
        "clv": None if clv is None else clamp(clv * 100),
        "rs": tanh_quality(row["rs_10d"], config.rs_scales["rs_10d"]),
        "fragility": None if fragility is None else clamp(100 - fragility),
    }

    def evaluate(components, weights, branch_checks, status, reason, evidence=None):
        available = sum(weights[key] for key, value in components.items() if value is not None)
        normalized = (
            {key: weights[key] / available for key, value in components.items() if value is not None}
            if available
            else {}
        )
        contributions = {key: components[key] * weight for key, weight in normalized.items()}
        quality = round(sum(contributions.values()), 4) if available else None
        return {
            "components": components,
            "weights": weights,
            "normalized_weights": normalized,
            "contributions": contributions,
            "checks": branch_checks,
            "quality_score": quality,
            "score": quality,
            "status": status,
            "reason": reason,
            "evidence": evidence or {},
        }

    if row["ma20_slope"] <= 0 or row["reference_price"] < row["ma20"]:
        status, reason = "INVALIDATED", "长期均线结构已失效"
    elif distance is not None and distance > config.entry_breakout_max_atr:
        status, reason = "EXTENDED", "突破后距原阻力过远，已超出执行窗口"
    elif all(checks.values()):
        status, reason = "CONFIRMED", "突破形态与确认条件均已满足"
    elif breakout:
        status, reason = "PULLING_BACK", "已突破，等待确认条件：" + "、".join(
            label
            for key, label in {
                "rs_score": "相对强度",
                "alpha_score": "Alpha",
                "path_score": "路径质量",
                "ma20_rising": "长期均线上升",
                "rs10_positive": "相对收益为正",
                "fragility": "脆弱性",
                "trend_score": "趋势质量",
                "extension": "突破ATR距离",
                "clv": "收盘位置",
            }.items()
            if not checks[key]
        )
    else:
        status, reason = "WAITING_PULLBACK", "等待突破形态"
    breakout_result = evaluate(
        {
            **shared,
            "breakout": setup["breakout_quality"],
            "extension": (
                None
                if distance is None
                else 100
                * gaussian(
                    distance, config.entry_breakout_distance_center_atr, config.entry_breakout_distance_width_atr
                )
            ),
            "volume": (
                None
                if row.get("volume_provisional") and row.get("projected_volume_ratio") is None
                else setup["volume_quality"]
            ),
            "path": row["path_score"],
        },
        config.breakout_entry_weights,
        checks,
        status,
        reason,
        {"support": level, "distance_atr": distance},
    )
    pullbacks = {}
    for kind in ENTRY_KINDS[1:]:
        evidence = context.get("pullbacks", {}).get(kind, {})
        reclaim, depth = evidence.get("reclaim_atr"), evidence.get("depth_atr")
        status = evidence.get("status", "WAITING_PULLBACK")
        branch_checks = {
            "recent_trend": context.get("recent_trend_date") is not None,
            "structure": bool(context.get("long_structure_healthy")) and evidence.get("support_intact", False),
            "recovery": bool(evidence.get("recovered")),
            "extension": reclaim is not None and reclaim <= config.entry_extended_atr,
        }
        components = {
            **shared,
            "reclaim": (
                None
                if reclaim is None
                else 100 * gaussian(reclaim, config.entry_reclaim_center_atr, config.entry_reclaim_width_atr)
            ),
            "pullback_depth": (
                None
                if depth is None
                else 100 * gaussian(depth, config.entry_pullback_center_atr, config.entry_pullback_width_atr)
            ),
            "distance": (
                None
                if reclaim is None
                else 100
                * gaussian(reclaim, config.entry_support_distance_center_atr, config.entry_support_distance_width_atr)
            ),
        }
        if evidence.get("support") is None:
            # Shared RS/CLV alone cannot score a setup without any known support.
            components = {key: None for key in components}
        pullbacks[kind] = evaluate(
            components,
            config.resume_entry_weights,
            branch_checks,
            status,
            evidence.get("reason", "历史数据不足，等待回踩资格与形态预热"),
            evidence,
        )
    results = {"breakout": breakout_result, **pullbacks}
    resume_result = max(
        pullbacks.values(),
        key=lambda r: (r["status"] == "CONFIRMED", r["quality_score"] if r["quality_score"] is not None else -1),
    )
    breakout_confirmed = breakout_result["status"] == "CONFIRMED"
    resume_confirmed = any(r["status"] == "CONFIRMED" for r in pullbacks.values())
    kind = (
        "BREAKOUT_AND_PULLBACK"
        if breakout_confirmed and resume_confirmed
        else "BREAKOUT" if breakout_confirmed else "PULLBACK_RESUME" if resume_confirmed else "NONE"
    )
    confirmed = [(key, value) for key, value in results.items() if value["status"] == "CONFIRMED"]
    selected = min(confirmed, key=lambda pair: (-(pair[1]["quality_score"] or 0), pair[0])) if confirmed else None
    return {
        "entry_primary": {"kind": selected[0], **selected[1]} if selected else None,
        "entry_score_semantics": "maximum_setup_quality_not_execution_or_probability",
        "entry_score": max(
            (r["quality_score"] for r in results.values() if r["quality_score"] is not None), default=None
        ),
        "entry_type": kind,
        "entry_version": 2,
        "entry_context": context,
        "entry_execution_ma5": context.get("ma5"),
        "entry_execution_ma10": context.get("ma10"),
        "entry_recent_trend_age": context.get("recent_trend_age"),
        **{
            f"entry_{key}_{field}": result["quality_score" if field == "score" else field]
            for key, result in results.items()
            for field in ("score", "status", "reason")
        },
        "entry_breakdown": {
            "breakout": breakout_result,
            "resume": resume_result,
            "pullbacks": pullbacks,
            "volume_provisional": row.get("volume_provisional", False),
            "parameters": {key: value for key, value in vars(config).items() if key.startswith("entry_")},
        },
    }
