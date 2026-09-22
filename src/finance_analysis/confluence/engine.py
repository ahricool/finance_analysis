"""Pure, auditable scoring; missing evidence is never a negative observation."""

from finance_analysis.confluence import config as c


def signal(key, facts=None, unavailable_reason="截至目标日期无正式数据"):
    weight = c.WEIGHTS[key]
    result = dict(
        source_module=c.SOURCE_MODULES[key],
        status="unavailable",
        weight=weight,
        score=None,
        trade_date=None,
        source_generated_at=None,
        evidence={},
        reasons=[unavailable_reason],
    )
    if not facts:
        return result
    status = "neutral"
    reasons = []
    if key == "industry":
        rank = facts.get("strength_rank")
        if rank is None:
            return result
        status = "positive" if rank <= c.TOP_INDUSTRY else "neutral"
        if facts.get("state") in {"WEAK", "COOLING"}:
            status = "negative"
        reasons.append(f"行业 {facts['industry_name']} 排名第 {rank}；状态 {facts.get('state')}")
    elif key == "trend":
        state, lifecycle = facts.get("state"), facts.get("trend_lifecycle")
        if state is None:
            return result
        fragility = facts.get("fragility_score")
        if state in {"WEAKENING", "BROKEN"} or (fragility is not None and fragility >= c.HIGH_FRAGILITY):
            status = "negative"
        elif state in {"CANDIDATE", "TRENDING"} and lifecycle in c.POSITIVE_LIFECYCLES:
            status = "positive"
        reasons.append(f"Lifecycle = {lifecycle or '缺失'}；State = {state}")
        if fragility is not None:
            reasons.append(f"Fragility = {fragility:g}" + ("（低脆弱性）" if fragility <= c.LOW_FRAGILITY else ""))
    elif key == "quant":
        rank, action = facts.get("universe_rank"), facts.get("signal")
        if rank is None and action is None:
            return result
        if str(action).upper() == "AVOID":
            status = "negative"
        elif str(action).upper() == "BUY" or (rank is not None and rank <= c.TOP_QUANT):
            status = "positive"
        reasons.append(f"Quant Rank = {rank if rank is not None else '缺失'}；Signal = {action or '缺失'}")
    elif key == "etf":
        rank = facts.get("rank")
        if rank is None:
            return result
        if facts.get("state") in {"WEAK", "EXHAUSTED", "COOLING"}:
            status = "negative"
        elif rank <= c.TOP_ETF and facts.get("is_candidate") and facts.get("action") in {"BUY", "HOLD"}:
            status = "positive"
        reasons.append(f"ETF {facts.get('code')} Rank = {rank}；State = {facts.get('state')}")
    else:
        net = facts.get("net_inflow")
        if net is None:
            return result
        status = "positive" if net > 0 else "negative" if net < 0 else "neutral"
        reasons.append(f"龙虎榜 {facts.get('range_days', 1)}D 榜净流入 = {net:g} CNY（最近一次记录，不累计重叠窗口）")
    if key == "trend" and facts.get("previous_rank") is not None:
        reasons.append(f"前次快照 {facts['previous_trade_date']} 排名 {facts['previous_rank']} → {facts['rank']}")
    for window in (1, 3, 5):
        change = facts.get(f"rank_change_{window}d")
        rank = facts.get("strength_rank", facts.get("rank"))
        if change is not None and rank is not None:
            reasons.append(f"{window}D 排名 {rank + change} → {rank}（仅解释，不重复加分）")
    points = round(weight * c.FACTORS[status], 4)
    reasons.append(f"{status}：{c.FACTORS[status]:g} × 权重 {weight} = {points:g} 分")
    return dict(
        result,
        status=status,
        score=points,
        trade_date=facts.get("trade_date"),
        source_generated_at=facts.get("generated_at", facts.get("updated_at")),
        evidence=facts,
        reasons=reasons,
    )


def aggregate(signals, rules=None):
    rules = rules if rules is not None else c.current_rules()
    available = [s for s in signals.values() if s["status"] != "unavailable"]
    weight = sum(s["weight"] for s in available)
    score = round(100 * sum(s["score"] for s in available) / weight, 2) if weight else None
    positive = sum(s["status"] == "positive" for s in available)
    count = len(available)
    return dict(
        confluence_score=score,
        available_weight=weight,
        available_signal_count=count,
        positive_signal_count=positive,
        eligible=count >= rules["min_signals"],
        strong_confluence=(
            count >= rules["strong_min_signals"]
            and positive >= rules["strong_min_positive"]
            and score is not None
            and score >= rules["strong_min_score"]
        ),
        signals=signals,
        reasons=[
            reason
            for key in sorted(signals, key=lambda k: -c.WEIGHTS[k])
            if signals[key]["status"] != "unavailable"
            for reason in signals[key]["reasons"]
        ],
    )
