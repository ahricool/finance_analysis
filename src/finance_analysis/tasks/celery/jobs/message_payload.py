"""Helpers for reconstructing notification messages from Celery-safe payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from finance_analysis.notification.messages import BotMessage, ChatType


def bot_message_from_payload(payload: Optional[Dict[str, Any]]) -> Optional[BotMessage]:
    if not payload:
        return None

    timestamp = payload.get("timestamp")
    parsed_timestamp = datetime.now()
    if isinstance(timestamp, str):
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp)
        except ValueError:
            pass

    return BotMessage(
        platform=str(payload.get("platform") or ""),
        message_id=str(payload.get("message_id") or ""),
        user_id=str(payload.get("user_id") or ""),
        user_name=str(payload.get("user_name") or ""),
        chat_id=str(payload.get("chat_id") or ""),
        chat_type=ChatType(payload.get("chat_type") or ChatType.UNKNOWN.value),
        content=str(payload.get("content") or ""),
        raw_content=str(payload.get("raw_content") or ""),
        mentioned=bool(payload.get("mentioned") or False),
        mentions=list(payload.get("mentions") or []),
        timestamp=parsed_timestamp,
        raw_data=dict(payload.get("raw_data") or {}),
    )


__all__ = ["bot_message_from_payload"]
