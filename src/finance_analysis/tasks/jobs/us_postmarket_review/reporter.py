# -*- coding: utf-8 -*-
"""Report persistence and notification for US post-market reviews."""

from __future__ import annotations

import logging
import os
from typing import Optional

from .models import (
    US_POSTMARKET_TASK_TYPE,
    US_POSTMARKET_TIMEZONE,
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
    """Saves the Markdown report, records calendar content, and sends notifications."""

    def __init__(
        self,
        *,
        notifier: Optional[object] = None,
        calendar_repo: Optional[object] = None,
        user_repo: Optional[object] = None,
    ) -> None:
        self.notifier = notifier
        self.calendar_repo = calendar_repo
        self.user_repo = user_repo
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

    def record_to_calendar(self, summary: USPostmarketReviewSummary) -> Optional[int]:
        try:
            repo = self._get_calendar_repo()
            uid = int(self._get_user_repo().ensure_default_admin())
            title = (
                f"美股收盘复盘 {summary.trading_date.isoformat()}："
                f"{market_regime_title(summary.market_regime)}"
            )
            existing = None
            if hasattr(repo, "get_by_type_and_date"):
                existing = repo.get_by_type_and_date(
                    type=US_POSTMARKET_TASK_TYPE,
                    day=summary.trading_date,
                    timezone_name=US_POSTMARKET_TIMEZONE,
                    uid=uid,
                )
            if existing is not None:
                updated = repo.update(
                    int(getattr(existing, "id")),
                    uid=uid,
                    title=title[:120],
                    content=summary.report,
                    type=US_POSTMARKET_TASK_TYPE,
                )
                entry = updated or existing
            else:
                entry = repo.create(
                    uid=uid,
                    time=summary.finished_at,
                    title=title[:120],
                    content=summary.report,
                    type=US_POSTMARKET_TASK_TYPE,
                )
            return int(getattr(entry, "id", 0) or 0)
        except Exception:
            logger.exception("写入美股收盘复盘日历失败")
            raise

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

    def _get_calendar_repo(self) -> object:
        if self.calendar_repo is None:
            from finance_analysis.database.repositories.calendar import CalendarRepo

            self.calendar_repo = CalendarRepo()
        return self.calendar_repo

    def _get_user_repo(self) -> object:
        if self.user_repo is None:
            from finance_analysis.database.repositories.user import UserRepository

            self.user_repo = UserRepository()
        return self.user_repo
