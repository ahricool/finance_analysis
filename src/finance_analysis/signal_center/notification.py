"""One report per completed market/day, shared by in-app and external notifications."""


def render(market, day, analysis, snapshot, search_evidence, screening=()):
    names = {c["symbol"]: c for c in snapshot["candidates"]}
    lines = [
        f"# 信号中心 · {'A股' if market == 'CN' else '美股'} · {day}",
        f"结论：{analysis['decision']} · 推荐 {len(analysis['recommendations'])}/3",
        "",
        analysis["thesis"],
    ]
    if analysis["no_trade_reason"]:
        lines.append(f"不交易原因：{analysis['no_trade_reason']}")
    for fact in analysis.get("evidence", []):
        lines.append(f"结论证据：{fact['field']} = {fact['value']}（{fact['data_as_of']}）：{fact['interpretation']}")
    if analysis["decision"] == "NO_TRADE" and not analysis.get("evidence"):
        for index, batch in enumerate(screening, 1):
            lines.append(f"初筛证据 · 桶{index} · 入围{len(batch['symbols'])}个：{batch['reason']}")
    for index, pick in enumerate(analysis["recommendations"], 1):
        candidate = names[pick["symbol"]]
        lines.extend(
            [
                "",
                f"## {index}. {candidate['name']}（{pick['symbol']}）· {candidate['instrument_type']}",
                f"信心：{pick['confidence']}",
                pick["thesis"],
                "证据：",
            ]
        )
        for evidence in pick["evidence"]:
            lines.append(
                f"- {evidence['field']} = {evidence['value']}（{evidence['data_as_of']}）："
                f"{evidence['interpretation']}"
            )
        for label, key in (("正向依据", "positive_signals"), ("风险", "risks"), ("失效条件", "invalidations")):
            lines.append(label + "：" + "；".join(pick[key]))
        for source in pick["external_sources"]:
            lines.append(
                f"外部来源：{source['title']} · {source['published_date'] or '发布日期未知'}\n"
                f"{source['url']}\n{source['excerpt']}"
            )
    missing = [
        key
        for key, source in snapshot["source_availability"].items()
        if source["status"] not in {"available", "unsupported"}
    ]
    if missing:
        lines.append("缺失来源：" + "、".join(missing))
    lines.append("最终轮搜索状态：" + search_evidence.get("status", "unverified") + "；外部摘录为模型引用，未逐篇核验。")
    return "\n".join(lines)
