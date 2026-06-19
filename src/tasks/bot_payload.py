# -*- coding: utf-8 -*-
"""JSON-safe BotMessage payload helpers for Celery tasks."""

from __future__ import annotations

from typing import Any, Dict, Optional

from bot.models import BotMessage


def bot_message_to_payload(message: Optional[BotMessage]) -> Optional[Dict[str, Any]]:
    if message is None:
        return None
    return {
        "platform": message.platform,
        "message_id": message.message_id,
        "user_id": message.user_id,
        "user_name": message.user_name,
        "chat_id": message.chat_id,
        "chat_type": message.chat_type.value if hasattr(message.chat_type, "value") else str(message.chat_type),
        "content": message.content,
        "raw_content": message.raw_content,
        "mentioned": message.mentioned,
        "mentions": list(message.mentions or []),
        "timestamp": message.timestamp.isoformat() if message.timestamp else None,
        "raw_data": dict(message.raw_data or {}),
    }

