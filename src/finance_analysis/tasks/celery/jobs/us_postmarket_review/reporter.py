# -*- coding: utf-8 -*-
"""Report persistence and notification for US post-market reviews."""

from __future__ import annotations

import logging
import os
from typing import Optional

from .models import (
    USPostmarketReviewSummary,
)

from finance_analysis.tasks.lifecycle import get_current_task_id

logger = logging.getLogger(__name__)


def market_regime_title(regime: str) -> str:
    mapping = {
        "risk_on": "Risk On",
        "risk_off": "Risk Off",
        "neutral": "Neutral",
    }
    return mapping.get(regime, "Neutral")


class USPostmarketReviewReporter:
    """Saves the Markdown report, records investment analysis, and sends notifications."""

    def __init__(
        self,
        *,
        notifier: Optional[object] = None,
        timeline_repo: Optional[object] = None,
    ) -> None:
        self.notifier = notifier
        self.timeline_repo = timeline_repo
        self._notifier_provided = notifier is not None

    def save_report_file(self, summary: USPostmarketReviewSummary) -> Optional[str]:
        try:
            notifier = self._get_notifier()
            filename = f"us_postmarket_review_{summary.trading_date.strftime('%Y%m%d')}.md"
            return str(notifier.save_report_to_file(summary.report, filename))
        except Exception as exc:
            logger.warning("保存美股收盘复盘报告文件失败: %s", exc, exc_info=True)
            summary.warnings.append(f"报告文件保存失败: {exc}")
            return None

    def record_report(self, summary) -> int:
        entry = self._get_timeline_repo().create(
            entry_type="us_postmarket",
            market="US",
            event_time=summary.finished_at,
            title=f"美股收盘复盘 {summary.trading_date.isoformat()}",
            summary=f"市场状态：{market_regime_title(summary.market_regime)}。复核收盘表现、持仓风险与下一交易日观察重点。",
            content=summary.report,
            importance="high",
            actionability="watch",
            source_run_id=get_current_task_id(),
            source_task="analysis_us_postmarket_review",
        )
        return entry.id

    def send_notification(
        self,
        summary: USPostmarketReviewSummary,
        *,
        send_notification: bool,
    ) -> bool:
        if not send_notification:
            return False
        if os.getenv("PYTEST_CURRENT_TEST") and not self._notifier_provided:
            logger.info("测试环境跳过真实美股收盘复盘通知")
            return False
        try:
            notifier = self._get_notifier()
            key = f"us_postmarket_review:{summary.trading_date.isoformat()}"
            sent = bool(
                notifier.send(
                    summary.report,
                    email_send_to_all=True,
                    route_type="report",
                    severity="info",
                    dedup_key=key,
                    cooldown_key=key,
                )
            )
            if not sent:
                summary.warnings.append("通知发送失败或无可用通知渠道")
            return sent
        except Exception as exc:
            logger.warning("发送美股收盘复盘通知失败: %s", exc, exc_info=True)
            summary.warnings.append(f"通知发送失败: {exc}")
            return False

    def _get_notifier(self) -> object:
        if self.notifier is None:
            from finance_analysis.notification.service import NotificationService

            self.notifier = NotificationService()
        return self.notifier

    def _get_timeline_repo(self) -> object:
        if self.timeline_repo is None:
            from finance_analysis.database.repositories.timeline import TimelineEntryRepo

            self.timeline_repo = TimelineEntryRepo()
        return self.timeline_repo
