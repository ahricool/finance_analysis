# -*- coding: utf-8 -*-
"""
Conversation Manager for Agent multi-turn chat.

Manages conversation sessions with TTL, storing message history and context.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.storage import get_db

logger = logging.getLogger(__name__)


@dataclass
class ConversationSession:
    """A single multi-turn conversation session."""
    session_id: str
    user_id: Optional[int] = None
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)

    def add_message(self, role: str, content: str, user_id: Optional[int] = None):
        """Add a message to the session history."""
        uid = user_id if user_id is not None else self.user_id
        get_db().save_conversation_message(self.session_id, role, content, uid=uid)
        self.last_active = datetime.now()

    def update_context(self, key: str, value: Any):
        """Update session context."""
        self.context[key] = value
        self.last_active = datetime.now()

    def get_history(self) -> List[Dict[str, Any]]:
        """Get message history."""
        messages = get_db().get_conversation_history(
            self.session_id,
            uid=self.user_id,
        )
        return messages


class ConversationManager:
    """Manages multiple conversation sessions with TTL."""

    def __init__(self, ttl_minutes: int = 30):
        self._sessions: Dict[str, ConversationSession] = {}
        self.ttl = timedelta(minutes=ttl_minutes)
        self._lock = threading.RLock()

    def get_or_create(self, session_id: str, user_id: Optional[int] = None) -> ConversationSession:
        """Get an existing session or create a new one."""
        with self._lock:
            self._cleanup_expired()

            if session_id not in self._sessions:
                self._sessions[session_id] = ConversationSession(
                    session_id=session_id,
                    user_id=user_id,
                )
                logger.info("Created new conversation session: %s", session_id)
            else:
                sess = self._sessions[session_id]
                if user_id and not sess.user_id:
                    sess.user_id = user_id
                sess.last_active = datetime.now()

            return self._sessions[session_id]

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: Optional[int] = None,
    ):
        """Add a message to a session."""
        session = self.get_or_create(session_id, user_id=user_id)
        session.add_message(role, content, user_id=user_id)

    def get_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Get message history for a session."""
        session = self.get_or_create(session_id)
        return session.get_history()

    def clear(self, session_id: str):
        """Clear a session."""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.info("Cleared conversation session: %s", session_id)

    def _cleanup_expired(self):
        """Remove expired sessions."""
        with self._lock:
            now = datetime.now()
            expired = [
                sid
                for sid, session in self._sessions.items()
                if now - session.last_active > self.ttl
            ]
            for sid in expired:
                del self._sessions[sid]
                logger.info("Cleaned up expired conversation session: %s", sid)


# Global instance
conversation_manager = ConversationManager()
