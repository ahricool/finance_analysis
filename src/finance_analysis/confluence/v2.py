"""Deterministic, source-native V2 evidence. No LLM, providers or strategy reruns."""

from math import isfinite
from statistics import fmean

VERSION = "confluence_v2_1"
WEIGHTS = {
    "macro": 15,
    "etf": 20,
    "industry": 15,
    "trend": 30,
    "quant": 7,
    "options": 5,
    "sentiment": 4,
    "dragon_tiger": 4,
}
PRIMARY = ("macro", "etf", "industry", "trend")
MODULES = {
    "macro": "macro",
    "etf": "etf_rotation",
    "industry": "industry_strength",
    "trend": "trend_following",
    "quant": "quant",
    "options": "options_intelligence",
    "sentiment": "market_sentiment",
    "dragon_tiger": "dragon_tiger_flow",
}


def rules():
    return dict(
        version=VERSION,
        macro_method="sector_macro_v1",
        weights=WEIGHTS.copy(),
        primary=list(PRIMARY),
        min_signals=2,
        strong_min_signals=2,
        strong_min_positive=2,
        strong_min_score=75,
        minimum_score=70,
        minimum_primary=2,
        max_signals=10,
        trend_method="mean_of_period_best_route",
        positive_threshold=65,
        negative_threshold=35,
    )


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def clamp(value):
    return min(100.0, max(0.0, float(value))) if number(value) else None


def average(values):
    valid = [v for v in values if number(v)]
    return fmean(valid) if valid else None


def trend_score(facts):
    periods = []
    for row in facts.get("periods", [facts]):
        f = row.get("features") or {}
        state = row.get("state")
        strength = clamp(row.get("alpha_score", row.get("trend_score")))
        if strength is not None:
            cap = {"IDLE": 20, "BROKEN": 20, "WEAKENING": 35, "WATCHING": 55}.get(state, 100)
            strength = min(strength, cap)
            fragility = clamp(row.get("fragility_score"))
            if fragility is not None:
                strength = min(strength, 100 - fragility)
        box = None
        if f.get("box_state") is not None:
            box = clamp(f.get("box_quality")) if f["box_state"] == "BOX_BREAKOUT" else 0.0
        if f.get("entry_type") == "BREAKOUT" and number(f.get("entry_score")):
            box = max(box or 0, clamp(f["entry_score"]))
        rebound = None
        if f.get("mr_state") is not None:
            rebound = clamp(f.get("mr_quality")) if f["mr_state"] == "MR_REBOUND" else 0.0
        routes = dict(trend=strength, breakout=box, rebound=rebound)
        valid = {k: v for k, v in routes.items() if number(v)}
        periods.append(
            dict(
                period=row.get("trend_period", 20),
                routes=routes,
                dominant=max(valid, key=valid.get) if valid else None,
                strength=max(valid.values()) if valid else None,
                state=state,
                lifecycle=row.get("trend_lifecycle"),
                fragility=row.get("fragility_score"),
                trade_date=row.get("trade_date"),
                rank=row.get("rank"),
            )
        )
    return average(p["strength"] for p in periods), periods


def evaluate(key, facts=None, reason="该日期无可用正式指标"):
    result = dict(
        source_module=MODULES[key],
        status="unavailable",
        weight=WEIGHTS[key],
        score=None,
        strength=None,
        normalized_weight=None,
        contribution=None,
        trade_date=None,
        source_generated_at=None,
        evidence={},
        reasons=[reason],
    )
    if not facts:
        return result
    evidence = dict(facts)
    strength = None
    reasons = []
    if key == "macro":
        strength = clamp(facts.get("adaptation_score"))
        reasons = [
            facts.get("adaptation_reason", "无行业宏观适配证据"),
            "整体风险偏好仅作背景；宏观15%使用所属行业适配度，非收益概率",
        ]
    elif key == "industry":
        rows = facts.get("industries", [facts])
        strength = average(clamp(r.get("strength_score")) for r in rows)
        evidence["industry_name"] = " / ".join(sorted({r.get("industry_name", "") for r in rows}))
        evidence["strength_score"] = strength
        states = {r.get("state") for r in rows}
        evidence["state"] = next(iter(states)) if len(states) == 1 else "行业状态分化"
        reasons = ["行业强度取所有可靠归属行业的正式强度均值，不挑最高分"]
    elif key == "etf":
        rows = facts.get("etfs", [])
        strength = average(clamp(r.get("composite_score")) for r in rows)
        reasons = ["关联ETF去重后等权使用正式综合分，近似关联保留依据；不依赖组合BUY/HOLD"]
    elif key == "trend":
        strength, evidence["matrix"] = trend_score(facts)
        reasons = [
            "20/40/60日分别比较趋势、突破、超跌反弹三条替代路线，取各周期最强路线后等权平均",
            "同周期的替代形态不重复叠加；没有对应核心字段的单元留空",
        ]
    elif key == "quant":
        value = facts.get("final_score")
        strength = clamp(value * 100) if number(value) and 0 <= value <= 1 else None
        if str(facts.get("signal", "")).lower() == "avoid" and strength is not None:
            strength = min(strength, 35)
        reasons = ["量化原生final_score（0–1）转为0–100；AVOID保留负向约束，排名仅作解释"]
    elif key == "options":
        scores = facts.get("scores") or {}
        # Activity is non-directional; high unusual activity must never become bullish evidence.
        risk_values = [(scores.get(k) or {}).get("value") for k in ("bearish_demand", "liquidity_risk")]
        strength = average(100 - clamp(v) for v in risk_values if number(v) and 0 <= v <= 100)
        reasons = [
            "期权采用保护需求与流动性风险的反向均值，表示风险支持度，不是看涨概率",
            "异常活跃度仅展示，不把成交活跃直接判为利多；保留原始置信标记",
        ]
    elif key == "sentiment":
        heat = clamp(facts.get("heat_score"))
        if heat is not None:
            strength = min(heat, {"COOLING": 35, "DIVERGENCE": 45, "CLIMAX": 65}.get(facts.get("state"), 100))
        reasons = ["市场热度为核心，降温/背离/高潮按状态约束；未知热度不参与"]
    elif key == "dragon_tiger":
        net = facts.get("net_inflow")
        if number(net):
            strength = 100.0 if net > 0 else 0.0 if net < 0 else 50.0
        reasons = ["最近一次龙虎榜净额方向；重叠窗口不累计，机构与游资仅展示"]
    if strength is None:
        return dict(result, evidence=evidence, reasons=reasons or ["来源存在，但核心指标缺失，权重不参与分母"])
    strength = round(strength, 4)
    return dict(
        result,
        strength=strength,
        score=round(WEIGHTS[key] * strength / 100, 6),
        status="positive" if strength >= 65 else "negative" if strength <= 35 else "neutral",
        trade_date=facts.get("trade_date"),
        source_generated_at=facts.get("generated_at", facts.get("updated_at")),
        evidence=evidence,
        reasons=reasons,
    )


def aggregate(signals, policy=None):
    policy = policy or rules()
    available = [s for s in signals.values() if s["strength"] is not None]
    total = sum(s["weight"] for s in available)
    for s in available:
        s["normalized_weight"] = round(100 * s["weight"] / total, 6)
        s["contribution"] = round(s["strength"] * s["weight"] / total, 6)
    score = round(sum(s["strength"] * s["weight"] / total for s in available), 2) if total else None
    core = [signals[k] for k in PRIMARY if signals[k]["strength"] is not None]
    positive = sum(s["status"] == "positive" for s in available)
    primary_positive = sum(s["status"] == "positive" for s in core)
    # Shared macro/sentiment alone cannot create thousands of identical stock signals.
    specific = any(signals[k]["strength"] is not None for k in ("trend", "quant", "options", "dragon_tiger"))
    eligible = (
        specific
        and len(core) >= policy["minimum_primary"]
        and primary_positive >= 2
        and score is not None
        and score >= policy["minimum_score"]
    )
    return dict(
        confluence_score=score,
        available_weight=total,
        available_signal_count=len(available),
        positive_signal_count=positive,
        eligible=eligible,
        strong_confluence=eligible and score >= policy["strong_min_score"],
        signals=signals,
        reasons=[
            f"主要证据 {len(core)}/4，正向 {primary_positive}；辅助证据仅使用实际可用指标",
            "缺失权重从分母移除，可用权重按比例归一；分数不是胜率",
        ],
    )


def confidence_key(row):
    core = [row["signals"][k] for k in PRIMARY if row["signals"][k]["strength"] is not None]
    agreement = sum(s["status"] == "positive" for s in core) / len(core) if core else 0
    return (-agreement, -len(core), -(row["confluence_score"] or 0), row.get("code", str(row["instrument_id"])))
