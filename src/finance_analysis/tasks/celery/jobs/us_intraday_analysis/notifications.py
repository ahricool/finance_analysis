# -*- coding: utf-8 -*-
"""Rendering and delivery of intraday signals to the calendar and notifier."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from .config import BEARISH_SIGNAL_TYPES, US_EASTERN
from .models import IntradaySignalResult

logger = logging.getLogger(__name__)


def render_calendar_content(signal: IntradaySignalResult) -> str:
    """Render the markdown body stored on a calendar entry."""
    result = signal.llm_result
    metrics = signal.metrics
    lines = [
        f"## {signal.symbol} 盘中异动",
        "",
        f"- 信号类型：{signal.signal_type}",
        f"- 规则强度：{metrics.get('rule_strength', '-')}",
        f"- 规则评分：{metrics.get('score', '-')}/{metrics.get('max_score', '-')}",
        f"- 最终决策：{result.get('final_decision', '-')}",
        f"- 是否通知：{bool(result.get('need_notification'))}",
        f"- 置信度：{result.get('confidence', '-')}",
        f"- 价格：{metrics.get('price', '-')}",
        f"- 5分钟涨跌幅：{metrics.get('change_5m', '-')}%",
        f"- 15分钟涨跌幅：{metrics.get('change_15m', '-')}%",
        f"- 相对 QQQ 15分钟强弱：{metrics.get('relative_to_qqq_15m', '-')}%",
        f"- 5分钟量比：{metrics.get('volume_ratio_5m', '-')}",
        f"- VWAP：{metrics.get('vwap', '-')}",
        "",
        "### LLM 判断",
        "",
        f"- 摘要：{result.get('summary', '-')}",
        f"- 理由：{result.get('reason', '-')}",
        f"- 风险：{result.get('risk', '-')}",
        f"- 建议：{result.get('suggestion', '-')}",
        "",
        "### 指标 JSON",
        "",
        f"```json\n{json.dumps(metrics, ensure_ascii=False, indent=2)}\n```",
    ]
    return "\n".join(lines)


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
    """Persists signals to the calendar and pushes user-facing notifications."""

    def record_to_calendar(self, signal: IntradaySignalResult) -> Optional[int]:
        """Create a calendar entry for the signal, returning its id if stored."""
        try:
            from finance_analysis.database.repositories.calendar import CalendarRepo
            from finance_analysis.database.repositories.user import UserRepository

            uid = UserRepository().ensure_default_admin()
            now = datetime.now(US_EASTERN)
            title = f"美股盘中异动：{signal.symbol} {signal.signal_type}"
            entry = CalendarRepo().create(
                uid=uid,
                time=now,
                title=title[:120],
                content=render_calendar_content(signal),
                type="us_intraday_signal",
            )
            return int(getattr(entry, "id", 0) or 0)
        except Exception as exc:
            logger.warning("写入美股盘中信号日历失败: %s", exc)
            return None

    def persist_signal(self, signal: IntradaySignalResult, signal_at: datetime) -> Optional[int]:
        """Store an intraday signal with minute evaluation enabled."""
        try:
            from finance_analysis.analysis.signal_evaluation import build_initial_evaluation
            from finance_analysis.database.repositories.signal import SignalRepository

            price = float(signal.metrics.get("price") or 0)
            if price <= 0:
                raise ValueError("signal price is missing")
            llm_result = getattr(signal, "llm_result", {}) or {}
            row = SignalRepository().create(
                market="US",
                code=signal.symbol,
                signal_type=signal.signal_type,
                signal_version=str(signal.metrics.get("rule_version") or "v1"),
                direction=str(llm_result.get("direction") or "neutral"),
                price=price,
                signal_at=signal_at,
                evaluation=build_initial_evaluation(supports_intraday=True),
            )
            return int(row.id)
        except Exception as exc:
            logger.warning("写入美股 Signal 失败: %s", exc)
            return None

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
