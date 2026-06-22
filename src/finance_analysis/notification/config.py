# -*- coding: utf-8 -*-
"""Notification-owned configuration and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import re
from typing import List, Optional, Tuple
from urllib.parse import unquote, urlparse

from finance_analysis.notification.noise_control import (
    NOTIFICATION_SEVERITIES,
    is_supported_notification_severity,
    parse_notification_quiet_hours,
    validate_notification_timezone,
)
from finance_analysis.config.env_parsing import env_bool, env_list, env_str


def has_ntfy_topic_endpoint(value: Optional[str]) -> bool:
    raw_url = (value or "").strip()
    if not raw_url:
        return False
    parsed = urlparse(raw_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return False
    return any(unquote(segment).strip() for segment in parsed.path.split("/") if segment)


def _parse_stock_email_groups() -> List[Tuple[List[str], List[str]]]:
    import os
    from finance_analysis.integrations.market_data.base import normalize_stock_code

    groups: dict[int, dict[str, list[str]]] = {}
    stock_re = re.compile(r"^STOCK_GROUP_(\d+)$", re.IGNORECASE)
    email_re = re.compile(r"^EMAIL_GROUP_(\d+)$", re.IGNORECASE)
    for key in os.environ:
        stock_match = stock_re.match(key)
        if stock_match:
            idx = int(stock_match.group(1))
            groups.setdefault(idx, {})["stocks"] = [
                normalize_stock_code(code.strip())
                for code in os.environ[key].split(",")
                if code.strip()
            ]
        email_match = email_re.match(key)
        if email_match:
            idx = int(email_match.group(1))
            groups.setdefault(idx, {})["emails"] = [
                email.strip()
                for email in os.environ[key].split(",")
                if email.strip()
            ]

    result: list[tuple[list[str], list[str]]] = []
    for idx in sorted(groups):
        group = groups[idx]
        stocks = group.get("stocks") or []
        emails = group.get("emails") or []
        if stocks and emails:
            result.append((stocks, emails))
    return result


@dataclass
class NotificationConfig:
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_message_thread_id: Optional[str] = None
    email_sender: Optional[str] = None
    email_sender_name: str = "Finance Analysis 分析助手"
    email_password: Optional[str] = None
    email_receivers: List[str] = field(default_factory=list)
    stock_email_groups: List[Tuple[List[str], List[str]]] = field(default_factory=list)
    ntfy_url: Optional[str] = None
    ntfy_token: Optional[str] = None
    custom_webhook_urls: List[str] = field(default_factory=list)
    custom_webhook_bearer_token: Optional[str] = None
    custom_webhook_body_template: Optional[str] = None
    webhook_verify_ssl: bool = True
    astrbot_url: Optional[str] = None
    astrbot_token: Optional[str] = None
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
        email_sender=env_str("EMAIL_SENDER") or None,
        email_password=env_str("EMAIL_PASSWORD") or None,
        email_receivers=env_list("EMAIL_RECEIVERS"),
        stock_email_groups=_parse_stock_email_groups(),
        ntfy_url=env_str("NTFY_URL") or None,
        ntfy_token=env_str("NTFY_TOKEN") or None,
        custom_webhook_urls=env_list("CUSTOM_WEBHOOK_URLS"),
        custom_webhook_bearer_token=env_str("CUSTOM_WEBHOOK_BEARER_TOKEN") or None,
        custom_webhook_body_template=env_str("CUSTOM_WEBHOOK_BODY_TEMPLATE") or None,
        webhook_verify_ssl=env_bool("WEBHOOK_VERIFY_SSL", True),
        astrbot_url=env_str("ASTRBOT_URL") or None,
        astrbot_token=env_str("ASTRBOT_TOKEN") or None,
    )
