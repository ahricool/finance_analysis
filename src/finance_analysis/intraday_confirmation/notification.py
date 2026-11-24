"""Render the stable intraday changes that merit an alert."""

from datetime import datetime

ALERT_ROUTE = "alert"
ALERT_SEVERITY = "warning"
PUSH_ITEMS_PER_GROUP = 5


def _confirm_label(row):
    conditions = row.get("conditions", {})
    routes = [
        label
        for key, label in (("opening_breakout", "开盘区间突破"), ("ma5_pullback", "MA5 回踩"))
        if conditions.get(key)
    ]
    label = " / ".join(routes) or "结构确认"
    if row.get("chase_risk") == "HIGH":
        label += "，追高风险高"
    return f"{row['code']}（{label}）"


def _section(label, lines, limit=None):
    visible = lines[:limit]
    section = [f"**{label}（{len(lines)}）**", *(f"- {line}" for line in visible)]
    if len(visible) < len(lines):
        section.append(f"- 另有 {len(lines) - len(visible)} 只，详见消息中心")
    return "\n".join(section)


def render_alert(trading_session, evaluated_at, confirmed, failed):
    local = datetime.fromisoformat(evaluated_at).astimezone(trading_session.opened.tzinfo)
    market_label = {"CN": "A 股", "US": "美股"}[trading_session.market]
    title = f"{market_label}盘中确认 · {local:%H:%M} · {len(confirmed) + len(failed)} 项变化"
    groups = (
        ("确认后失效", [f"{row['code']}（跌破开盘区间低点）" for row in failed]),
        ("首次确认", [_confirm_label(row) for row in confirmed]),
    )
    heading = f"**{title}**"
    full = [_section(label, lines) for label, lines in groups if lines]
    push = [_section(label, lines, PUSH_ITEMS_PER_GROUP) for label, lines in groups if lines]
    link = "[查看盘中确认](/research/intraday-confirmation)"
    return title, "\n\n".join([heading, *full, link]), "\n\n".join([heading, *push])
