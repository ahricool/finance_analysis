# -*- coding: utf-8 -*-
"""Notification channel senders."""

from finance_analysis.notification.senders.astrbot import AstrbotSender
from finance_analysis.notification.senders.custom_webhook import CustomWebhookSender
from finance_analysis.notification.senders.email import EmailSender
from finance_analysis.notification.senders.ntfy import NtfySender, resolve_ntfy_endpoint
from finance_analysis.notification.senders.telegram import TelegramSender

__all__ = [
    "AstrbotSender",
    "CustomWebhookSender",
    "EmailSender",
    "NtfySender",
    "TelegramSender",
    "resolve_ntfy_endpoint",
]
