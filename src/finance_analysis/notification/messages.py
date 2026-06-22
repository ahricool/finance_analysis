# -*- coding: utf-8 -*-
"""Source message models used for notification routing.

These lightweight data models carry the context of the request that triggered an
analysis (who asked, in which conversation). They are intentionally
platform-agnostic and do not depend on any messaging integration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List


class ChatType(str, Enum):
    """Conversation type for a source message."""

    GROUP = "group"
    PRIVATE = "private"
    UNKNOWN = "unknown"


@dataclass
class BotMessage:
    """Unified source-message model.

    Carries the metadata of the request that initiated an analysis so that
    downstream notifications can be routed back to the original requester.
    """

    platform: str
    message_id: str
    user_id: str
    user_name: str
    chat_id: str
    chat_type: ChatType
    content: str
    raw_content: str = ""
    mentioned: bool = False
    mentions: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    raw_data: Dict[str, Any] = field(default_factory=dict)


__all__ = ["BotMessage", "ChatType"]
