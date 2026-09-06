# -*- coding: utf-8 -*-
"""Rendering and notification of ephemeral intraday alerts."""

from __future__ import annotations

import logging

from .config import BEARISH_SIGNAL_TYPES
from .models import IntradaySignalResult

logger = logging.getLogger(__name__)


def render_notification(signal: IntradaySignalResult) -> str:
    """Render the compact alert body pushed to the notification channel."""
    result = signal.llm_result
    metrics = signal.metrics
    return "\n".join(
        [
            f"**美股盘中异动：{signal.symbol}**",
            "",
            f"- 信号：{signal.signal_type}",
            (
                f"- 规则：{metrics.get('rule_strength', '-')} "
                f"{metrics.get('score', '-')}/{metrics.get('max_score', '-')}"
            ),
            f"- 决策：{result.get('final_decision', '-')}",
            f"- 置信度：{result.get('confidence', '-')}",
            f"- 摘要：{result.get('summary', '-')}",
            f"- 理由：{result.get('reason', '-')}",
            f"- 风险：{result.get('risk', '-')}",
            f"- 建议：{result.get('suggestion', '-')}",
            "",
            (
                f"价格 {metrics.get('price', '-')} | 5m {metrics.get('change_5m', '-')}% | "
                f"15m {metrics.get('change_15m', '-')}% | "
                f"相对 QQQ {metrics.get('relative_to_qqq_15m', '-')}% | "
                f"量比 {metrics.get('volume_ratio_5m', '-')}"
            ),
        ]
    )


class SignalReporter:
    """Pushes user-facing notifications."""

    def send_notification(self, signal: IntradaySignalResult) -> bool:
        """Send the alert through the notification service; report success."""
        try:
            from finance_analysis.notification.service import NotificationService

            rule_severity = str(signal.metrics.get("severity") or "").lower()
            severity = "warning"
            if signal.signal_type in BEARISH_SIGNAL_TYPES and rule_severity == "high":
                severity = "error"
            generation = int(signal.metrics.get("state_generation") or 1)
            return NotificationService().send(
                render_notification(signal),
                email_stock_codes=[signal.symbol],
                route_type="alert",
                severity=severity,
                dedup_key=f"us_intraday:{signal.symbol}:{signal.signal_type}:{generation}",
                cooldown_key=f"us_intraday:{signal.symbol}:{signal.signal_type}:{generation}",
            )
        except Exception as exc:
            logger.warning("发送美股盘中信号通知失败: %s", exc)
            return False
