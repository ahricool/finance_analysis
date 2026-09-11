"""Report persistence and one aggregated notification for pre-close reviews."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from finance_analysis.notification.service import NotificationResult

from .config import ACTION_LABELS, SECTOR_CONTINUITY_LABELS
from .models import PreCloseReviewSummary


logger = logging.getLogger(__name__)

_ACTION_PRIORITY = {
    "exit_or_large_reduce": 5,
    "reduce": 4,
    "add_on_condition": 3,
    "watch": 2,
    "maintain": 1,
}


class ASharePreCloseReporter:

    def __init__(
        self,
        *,
        notifier: Optional[Any] = None,
    ) -> None:
        self.notifier = notifier
        self._notifier_provided = notifier is not None

    def send_notification(
        self,
        summary: PreCloseReviewSummary,
        *,
        send_notification: bool,
    ) -> NotificationResult:
        if os.getenv("PYTEST_CURRENT_TEST") and not self._notifier_provided:
            logger.info("测试环境跳过真实 A 股收盘前复核通知")
            return NotificationResult()
        try:
            notifier = self._get_notifier()
            key = f"a_share_pre_close_review:{summary.trading_date.isoformat()}"
            result = notifier.send(
                content=render_report(summary),
                push_content=render_notification(summary),
                push=send_notification,
                route_type="report",
                severity="warning" if summary.risk_state in {"high", "elevated"} else "info",
                dedup_key=key,
                cooldown_key=key,
            )
            if result.notification_id is None:
                logger.warning("消息未能写入 notification")
            return result
        except Exception as exc:
            logger.warning("发送 A 股收盘前复核通知失败: %s", exc, exc_info=True)
            return NotificationResult()

    def _get_notifier(self) -> Any:
        if self.notifier is None:
            from finance_analysis.notification.service import NotificationService

            self.notifier = NotificationService()
        return self.notifier


def render_report(summary: PreCloseReviewSummary) -> str:
    decision = summary.decision
    market = decision.get("market_summary", {})
    lines = [
        f"# A股收盘前持仓与市场复核 - {summary.trading_date.isoformat()}",
        "",
        "## 1. 当前大盘状态",
        "",
        f"- 市场状态：{summary.market_state}",
        f"- 成交状态：{summary.turnover_state}",
        f"- 风险状态：{summary.risk_state}",
        f"- 结论：{market.get('conclusion') or '数据不足，维持审慎观察'}",
        *[f"- 依据：{item}" for item in summary.market_rationale],
        "",
        "## 2. 强势板块与持续性",
        "",
    ]
    if summary.strong_sectors:
        lines.extend(
            f"- {item.name} {item.change_pct:+.2f}%："
            f"{SECTOR_CONTINUITY_LABELS.get(item.continuity, item.continuity)}；{item.rationale}"
            for item in summary.strong_sectors
        )
    else:
        lines.append("- 板块数据不足，未形成可靠强势板块判断。")
    lines.extend(["", "## 3. 主要风险", ""])
    risks = decision.get("risks") or []
    lines.extend([f"- {item}" for item in risks] or ["- 暂无额外模型风险提示，仍需关注尾盘波动。"])
    lines.extend(["", "## 4. 当前持仓与调整建议", ""])
    holdings = decision.get("holdings") or []
    if holdings:
        for item in holdings:
            lines.append(f"- {item.get('code')} {item.get('name')}：{format_action(item)}")
            if item.get("rationale"):
                lines.append(f"  - 依据：{item['rationale']}")
            if item.get("condition"):
                lines.append(f"  - 条件：{item['condition']}")
            if item.get("invalidation"):
                lines.append(f"  - 失效：{item['invalidation']}")
    else:
        lines.append("- 当前持仓表中没有数量大于 0 的 A 股持仓。")
    lines.extend(["", "## 5. 候选观察机会", ""])
    candidates = decision.get("candidates") or []
    lines.extend(
        [
            f"- {item.get('code')} {item.get('name')}：观察；{item.get('rationale') or '-'}；"
            f"触发条件：{item.get('condition') or '-'}"
            for item in candidates
        ]
        or ["- 未形成可靠候选，或数据质量不足。"]
    )
    lines.extend(["", "## 6. 判断失效条件", ""])
    invalidations = decision.get("invalidation_conditions") or []
    lines.extend([f"- {item}" for item in invalidations] or ["- 尾盘市场宽度和指数方向发生明显反转。"])
    lines.extend(
        [
            "",
            "## 7. 数据完整性与置信度",
            "",
            f"- 置信度：{decision.get('confidence', summary.data_quality.confidence)}",
            f"- 行情新鲜：{'是' if summary.data_quality.fresh_quotes else '否'}",
            f"- 行情覆盖：{summary.data_quality.market_rows} 行；持仓覆盖 "
            f"{summary.data_quality.holding_coverage}/{summary.data_quality.holding_total}",
            f"- 说明：{decision.get('data_note') or '-'}",
        ]
    )
    lines.extend(f"- 数据提示：{item}" for item in summary.data_quality.issues)
    lines.extend(f"- 运行警告：{item}" for item in summary.warnings)
    lines.extend(
        [
            "",
            "提示：本任务仅提供分析建议，不自动下单。请结合当日新增持仓及 A 股 T+1 规则，"
            "自行确认 14:30-15:00 的实际可卖数量。",
        ]
    )
    return "\n".join(lines).strip()


def render_notification(summary: PreCloseReviewSummary) -> str:
    decision = summary.decision
    market = decision.get("market_summary", {})
    sectors = (
        "、".join(
            f"{item.name}({SECTOR_CONTINUITY_LABELS.get(item.continuity, item.continuity)})"
            for item in summary.strong_sectors[:3]
        )
        or "数据不足"
    )
    holdings = sorted(
        decision.get("holdings") or [],
        key=lambda item: _ACTION_PRIORITY.get(str(item.get("action")), 0),
        reverse=True,
    )
    key_holdings = (
        "；".join(f"{item.get('code')} {item.get('name')}：{format_action(item)}" for item in holdings[:4])
        or "无 A 股持仓"
    )
    risks = "；".join((decision.get("risks") or [])[:3]) or "关注尾盘波动"
    quality_warning = ""
    if summary.data_quality.confidence == "low" or summary.data_quality.issues:
        quality_warning = "\n数据提示：" + "；".join(summary.data_quality.issues[:3] or ["低置信度降级结果"])
    return (
        f"# A股收盘前复核 {summary.trading_date.isoformat()}\n\n"
        f"市场：{market.get('conclusion') or summary.market_state}；风险 {summary.risk_state}；"
        f"成交 {summary.turnover_state}\n"
        f"强势板块：{sectors}\n"
        f"持仓重点：{key_holdings}\n"
        f"主要风险：{risks}{quality_warning}\n\n"
        "请结合当日新增持仓和 A 股 T+1 规则，自行确认实际可卖数量；本任务不自动下单。"
    )


def format_action(item: dict[str, Any]) -> str:
    action = str(item.get("action") or "watch")
    label = ACTION_LABELS.get(action, "观察")
    minimum = item.get("percent_min")
    maximum = item.get("percent_max")
    if minimum is None or maximum is None:
        return label
    return f"{label}当前持仓的 {minimum}%-{maximum}%"


__all__ = ["ASharePreCloseReporter", "render_notification", "render_report"]
