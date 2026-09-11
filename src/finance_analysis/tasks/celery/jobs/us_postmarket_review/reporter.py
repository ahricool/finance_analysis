# -*- coding: utf-8 -*-
"""Report persistence and notification for US post-market reviews."""

from __future__ import annotations

import logging
import os
from typing import Optional

from .models import (
    USPostmarketReviewSummary,
)


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
    ) -> None:
        self.notifier = notifier
        self._notifier_provided = notifier is not None

    def send_notification(
        self,
        summary: USPostmarketReviewSummary,
        *,
        send_notification: bool,
    ) -> bool:
        if os.getenv("PYTEST_CURRENT_TEST") and not self._notifier_provided:
            logger.info("测试环境跳过真实美股收盘复盘通知")
            return False
        try:
            notifier = self._get_notifier()
            key = f"us_postmarket_review:{summary.trading_date.isoformat()}"
            sent = bool(
                notifier.send(
                    summary.report,
                    push=send_notification,
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
