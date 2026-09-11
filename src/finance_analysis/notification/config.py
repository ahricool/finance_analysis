# -*- coding: utf-8 -*-
"""Notification-owned configuration and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import List, Optional
from urllib.parse import unquote, urlparse

from finance_analysis.notification.noise_control import (
    NOTIFICATION_SEVERITIES,
    is_supported_notification_severity,
    parse_notification_quiet_hours,
    validate_notification_timezone,
)
from finance_analysis.config.env_parsing import env_bool, env_str


def has_ntfy_topic_endpoint(value: Optional[str]) -> bool:
    raw_url = (value or "").strip()
    if not raw_url:
        return False
    parsed = urlparse(raw_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return False
    return any(unquote(segment).strip() for segment in parsed.path.split("/") if segment)


@dataclass
class NotificationConfig:
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_message_thread_id: Optional[str] = None
    ntfy_url: Optional[str] = None
    ntfy_token: Optional[str] = None
    webhook_verify_ssl: bool = True
    notification_report_channels: List[str] = field(default_factory=list)
    notification_alert_channels: List[str] = field(default_factory=list)
    notification_system_error_channels: List[str] = field(default_factory=list)
    notification_dedup_ttl_seconds: int = 0
    notification_cooldown_seconds: int = 0
    notification_quiet_hours: str = ""
    notification_timezone: str = ""
    notification_min_severity: str = ""
    notification_daily_digest_enabled: bool = False

    def validate(self) -> list[str]:
        issues: list[str] = []
        if self.ntfy_url and not has_ntfy_topic_endpoint(self.ntfy_url):
            issues.append("NTFY_URL 必须包含 topic path，例如 https://ntfy.sh/my-topic")
        if self.notification_quiet_hours:
            try:
                parse_notification_quiet_hours(self.notification_quiet_hours)
            except ValueError as exc:
                issues.append(f"通知静默时段配置无效：{exc}")
        if self.notification_timezone:
            try:
                validate_notification_timezone(self.notification_timezone)
            except ValueError as exc:
                issues.append(f"通知时区配置无效：{exc}")
        if self.notification_min_severity and not is_supported_notification_severity(self.notification_min_severity):
            issues.append(f"通知最低级别配置无效，允许值：{', '.join(NOTIFICATION_SEVERITIES)}")
        return issues


@lru_cache(maxsize=1)
def get_notification_config() -> NotificationConfig:
    return NotificationConfig(
        telegram_bot_token=env_str("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=env_str("TELEGRAM_CHAT_ID") or None,
        telegram_message_thread_id=env_str("TELEGRAM_MESSAGE_THREAD_ID") or None,
        ntfy_url=env_str("NTFY_URL") or None,
        ntfy_token=env_str("NTFY_TOKEN") or None,
        webhook_verify_ssl=env_bool("WEBHOOK_VERIFY_SSL", True),
    )
