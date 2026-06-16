# -*- coding: utf-8 -*-
"""Conversation-message and LLM-usage storage methods for DatabaseManager.

Split out of :mod:`src.db.session` to keep the manager focused. These methods
rely on ``self.session_scope`` provided by :class:`src.db.session.DatabaseManager`.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, delete, desc, func, or_, select

from src.db.base import ensure_aware_datetime
from src.models import ConversationMessage, LLMUsage
from src.time_utils import utc_isoformat, utc_now


class ConversationUsageMixin:
    """Conversation history and LLM token-usage storage helpers."""

    def save_conversation_message(
        self,
        session_id: str,
        role: str,
        content: str,
        uid: Optional[int] = None,
    ) -> None:
        """
        保存 Agent 对话消息
        """
        with self.session_scope() as session:
            msg = ConversationMessage(
                uid=uid,
                session_id=session_id,
                role=role,
                content=content,
            )
            session.add(msg)

    def get_conversation_history(
        self,
        session_id: str,
        limit: int = 20,
        uid: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取 Agent 对话历史
        """
        with self.session_scope() as session:
            stmt = select(ConversationMessage).filter(
                ConversationMessage.session_id == session_id
            )
            if uid is not None:
                stmt = stmt.where(ConversationMessage.uid == uid)
            stmt = stmt.order_by(ConversationMessage.created_at.desc()).limit(limit)
            messages = session.execute(stmt).scalars().all()

            # 倒序返回，保证时间顺序
            return [{"role": msg.role, "content": msg.content} for msg in reversed(messages)]

    def conversation_session_exists(
        self, session_id: str, uid: Optional[int] = None
    ) -> bool:
        """Return True when at least one message exists for the given session."""
        with self.session_scope() as session:
            stmt = select(ConversationMessage.id).where(
                ConversationMessage.session_id == session_id
            )
            if uid is not None:
                stmt = stmt.where(ConversationMessage.uid == uid)
            stmt = stmt.limit(1)
            return session.execute(stmt).scalar() is not None

    def get_chat_sessions(
        self,
        limit: int = 50,
        session_prefix: Optional[str] = None,
        extra_session_ids: Optional[List[str]] = None,
        restrict_uid: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取聊天会话列表（从 conversation_messages 聚合）

        Args:
            limit: Maximum number of sessions to return.
            session_prefix: If provided, only return sessions whose session_id
                starts with this prefix.  Used for per-user isolation (e.g.
                ``"telegram_12345"``).
            extra_session_ids: Optional exact session ids to include in
                addition to the scoped prefix.

        Returns:
            按最近活跃时间倒序的会话列表，每条包含 session_id, title, message_count, last_active
        """
        from sqlalchemy import func

        with self.session_scope() as session:
            normalized_prefix = None
            if session_prefix:
                normalized_prefix = session_prefix if session_prefix.endswith(":") else f"{session_prefix}:"
            exact_ids = [sid for sid in (extra_session_ids or []) if sid]

            # 聚合每个 session 的消息数和最后活跃时间
            base = (
                select(
                    ConversationMessage.session_id,
                    func.count(ConversationMessage.id).label("message_count"),
                    func.min(ConversationMessage.created_at).label("created_at"),
                    func.max(ConversationMessage.created_at).label("last_active"),
                )
            )
            conditions = []
            if normalized_prefix:
                conditions.append(ConversationMessage.session_id.startswith(normalized_prefix))
            if exact_ids:
                conditions.append(ConversationMessage.session_id.in_(exact_ids))
            if conditions:
                base = base.where(or_(*conditions))
            if restrict_uid is not None:
                base = base.where(ConversationMessage.uid == restrict_uid)
            stmt = (
                base
                .group_by(ConversationMessage.session_id)
                .order_by(desc(func.max(ConversationMessage.created_at)))
                .limit(limit)
            )
            rows = session.execute(stmt).all()

            results = []
            for row in rows:
                sid = row.session_id
                # 取该会话第一条 user 消息作为标题
                first_scope = and_(
                    ConversationMessage.session_id == sid,
                    ConversationMessage.role == "user",
                )
                if restrict_uid is not None:
                    first_scope = and_(
                        first_scope,
                        ConversationMessage.uid == restrict_uid,
                    )
                first_user_msg = session.execute(
                    select(ConversationMessage.content)
                    .where(first_scope)
                    .order_by(ConversationMessage.created_at)
                    .limit(1)
                ).scalar()
                title = (first_user_msg or "新对话")[:60]

                results.append({
                    "session_id": sid,
                    "title": title,
                    "message_count": row.message_count,
                    "created_at": utc_isoformat(row.created_at),
                    "last_active": utc_isoformat(row.last_active),
                })
            return results

    def get_conversation_messages(
        self,
        session_id: str,
        limit: int = 100,
        uid: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取单个会话的完整消息列表（用于前端恢复历史）
        """
        with self.session_scope() as session:
            stmt = select(ConversationMessage).where(
                ConversationMessage.session_id == session_id
            )
            if uid is not None:
                stmt = stmt.where(ConversationMessage.uid == uid)
            stmt = stmt.order_by(ConversationMessage.created_at).limit(limit)
            messages = session.execute(stmt).scalars().all()
            return [
                {
                    "id": str(msg.id),
                    "role": msg.role,
                    "content": msg.content,
                    "created_at": utc_isoformat(msg.created_at),
                }
                for msg in messages
            ]

    def delete_conversation_session(
        self, session_id: str, uid: Optional[int] = None
    ) -> int:
        """
        删除指定会话的所有消息

        Returns:
            删除的消息数
        """
        with self.session_scope() as session:
            cond = ConversationMessage.session_id == session_id
            if uid is not None:
                cond = and_(cond, ConversationMessage.uid == uid)
            result = session.execute(delete(ConversationMessage).where(cond))
            return result.rowcount

    # ------------------------------------------------------------------
    # LLM usage tracking
    # ------------------------------------------------------------------

    def record_llm_usage(
        self,
        call_type: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        stock_code: Optional[str] = None,
        uid: Optional[int] = None,
    ) -> None:
        """Append one LLM call record to llm_usage."""
        row = LLMUsage(
            uid=uid,
            call_type=call_type,
            model=model or "unknown",
            stock_code=stock_code,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        with self.session_scope() as session:
            session.add(row)

    def get_llm_usage_summary(
        self,
        from_dt: datetime,
        to_dt: datetime,
        uid: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return aggregated token usage between from_dt and to_dt.

        Returns a dict with keys:
          total_calls, total_tokens,
          by_call_type: list of {call_type, calls, total_tokens},
          by_model:     list of {model, calls, total_tokens}
        """
        from_dt = ensure_aware_datetime(from_dt) or utc_now()
        to_dt = ensure_aware_datetime(to_dt) or utc_now()
        with self.session_scope() as session:
            base_filter = and_(
                LLMUsage.called_at >= from_dt,
                LLMUsage.called_at <= to_dt,
            )
            if uid is not None:
                base_filter = and_(base_filter, LLMUsage.uid == uid)

            # Overall totals
            totals = session.execute(
                select(
                    func.count(LLMUsage.id).label("calls"),
                    func.coalesce(func.sum(LLMUsage.total_tokens), 0).label("tokens"),
                ).where(base_filter)
            ).one()

            # Breakdown by call_type
            by_type_rows = session.execute(
                select(
                    LLMUsage.call_type,
                    func.count(LLMUsage.id).label("calls"),
                    func.coalesce(func.sum(LLMUsage.total_tokens), 0).label("tokens"),
                )
                .where(base_filter)
                .group_by(LLMUsage.call_type)
                .order_by(desc(func.sum(LLMUsage.total_tokens)))
            ).all()

            # Breakdown by model
            by_model_rows = session.execute(
                select(
                    LLMUsage.model,
                    func.count(LLMUsage.id).label("calls"),
                    func.coalesce(func.sum(LLMUsage.total_tokens), 0).label("tokens"),
                )
                .where(base_filter)
                .group_by(LLMUsage.model)
                .order_by(desc(func.sum(LLMUsage.total_tokens)))
            ).all()

        return {
            "total_calls": totals.calls,
            "total_tokens": totals.tokens,
            "by_call_type": [
                {"call_type": r.call_type, "calls": r.calls, "total_tokens": r.tokens}
                for r in by_type_rows
            ],
            "by_model": [
                {"model": r.model, "calls": r.calls, "total_tokens": r.tokens}
                for r in by_model_rows
            ],
        }

