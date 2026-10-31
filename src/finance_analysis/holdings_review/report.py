"""One Markdown report per user and market; built from the same saved structured decision."""

from .decision import sources
from .context import stamp
from finance_analysis.market_review.trading_calendar import get_market_now

ACTIONS = {"HOLD": "维持", "BUY": "加仓", "REDUCE": "减仓", "SELL": "退出", "WATCH": "观察"}
STATES = {"RISK_ON": "偏强", "NEUTRAL": "均衡", "RISK_OFF": "偏弱", "UNCERTAIN": "待确认"}


def clean(value):
    return str(value or "").replace("\r", " ").replace("\n", " ").replace("|", "／").strip()


def render_markdown(context, decision, evidence):
    market, day = context["market"], context["trade_date"]
    holdings = {p["position_id"]: p for p in context["holdings"]}
    observed = get_market_now(market.lower(), stamp(context["as_of"]))
    local_stamp = observed.strftime("%Y-%m-%d %H:%M") + (" 北京时间" if market == "CN" else " 纽约时间")
    lines = [
        f"# {'A股' if market == 'CN' else '美股'}持仓复盘 · {day}",
        "",
        f"观察时点：{local_stamp} · 收盘前50分钟 · {'规则降级' if decision['degraded'] else 'LLM复盘'}",
        "",
        "## 市场结论",
        f"**{STATES[decision['market_state']]}** · 置信度 {decision['confidence']}",
        clean(decision["conclusion"]),
        "",
        "## 板块强弱",
    ]
    lines += [
        f"- **{clean(row['name'])}**（{row['strength']}）：{clean(row['rationale'])}" for row in decision["sectors"]
    ] or ["- 未形成可靠板块判断。"]
    lines += ["", "## 持仓操作建议"]
    for row in decision["positions"]:
        holding = holdings[row["position_id"]]
        percent = f"当前持仓的 {row['change_pct']:g}%" if row["change_pct"] else ""
        lines += [
            f"### {clean(holding['name'])} · {row['symbol']} · {ACTIONS[row['action']]} {percent}",
            f"- 账户：{clean(holding.get('account_name') or holding.get('account_id'))}；"
            f"数量 {holding.get('quantity', '—')}，成本 {holding.get('average_cost', '—')}，"
            f"快照现价 {holding.get('current_price') if holding.get('current_price') is not None else '缺失'}",
            f"- 依据：{clean(row['rationale'])}",
        ]
        if row["condition"]:
            lines.append(f"- 条件：{clean(row['condition'])}")
        if row["invalidation"]:
            lines.append(f"- 失效：{clean(row['invalidation'])}")
    if not decision["positions"]:
        lines.append("当前市场没有已登记持仓，不生成加仓或新建仓建议。")
    lines += ["", "## 主要风险"]
    lines += [
        f"- **{clean(row['title'])}**（{row['severity']}）：{clean(row['detail'])}" for row in decision["risks"]
    ] or ["- 仍需关注尾盘行情变化。"]
    lines += ["", "## 后续观察", *[f"- {clean(text)}" for text in decision["watchpoints"]]]
    lines += ["", "## 数据与检索"]
    lines += [f"- {clean(item)}" for item in context["data_quality"]]
    lines.append(
        "- 联网核验："
        + {
            "confirmed": "取得工具执行证据",
            "unverified": "检索尚未取得可验证证据",
            "unavailable": "当前后端不可用",
        }.get(evidence.get("status"), "未取得证据")
    )
    lines += [
        f"- [{clean(row['title']).replace('[', '').replace(']', '')}](<{row['url']}>)" for row in sources(evidence)
    ]
    lines += ["", "建议仅针对已有持仓，不自动执行。A股当日买入部分受T+1约束，请核对券商实际可卖数量。"]
    return "\n".join(lines)
