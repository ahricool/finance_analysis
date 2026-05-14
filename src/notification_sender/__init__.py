# -*- coding: utf-8 -*-
"""
===================================
通知发送层模块
===================================

提供各种通知发送服务
"""

from .astrbot_sender import AstrbotSender
from .custom_webhook_sender import CustomWebhookSender
from .email_sender import EmailSender
from .ntfy_sender import NtfySender, resolve_ntfy_endpoint
from .telegram_sender import TelegramSender
