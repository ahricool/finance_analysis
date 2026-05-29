# -*- coding: utf-8 -*-
"""
===================================
平台适配器模块
===================================

包含各平台的 Webhook 处理和消息解析逻辑。
"""

from bot.platforms.base import BotPlatform

ALL_PLATFORMS: dict = {}

__all__ = [
    'BotPlatform',
    'ALL_PLATFORMS',
]
