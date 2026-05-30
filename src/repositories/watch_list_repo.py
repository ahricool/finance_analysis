# -*- coding: utf-8 -*-
"""Repository for watch_list (自选股) CRUD operations."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import select

from src.services.market_type_utils import normalize_market_type
from sqlalchemy.orm import Session

from src.storage import DatabaseManager, WatchListItem


def get_db() -> DatabaseManager:
    return DatabaseManager.get_instance()


class WatchListRepo:
    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or get_db()

    # ── Read ──────────────────────────────────────────────────────────────────

    def list_all(self, user_id: Optional[str] = None) -> List[WatchListItem]:
        with self.db.get_session() as session:
            stmt = select(WatchListItem).order_by(
                WatchListItem.is_favorite.desc(),
                WatchListItem.created_at,
            )
            if user_id is not None:
                stmt = stmt.where(WatchListItem.user_id == user_id)
            return session.execute(stmt).scalars().all()

    def get_by_id(self, item_id: int, user_id: Optional[str] = None) -> Optional[WatchListItem]:
        with self.db.get_session() as session:
            obj = session.get(WatchListItem, item_id)
            if obj is None:
                return None
            if user_id is not None and obj.user_id != user_id:
                return None
            return obj

    def get_by_code(self, code: str, user_id: Optional[str] = None) -> Optional[WatchListItem]:
        with self.db.get_session() as session:
            stmt = select(WatchListItem).where(WatchListItem.code == code.upper())
            if user_id is not None:
                stmt = stmt.where(WatchListItem.user_id == user_id)
            return session.execute(stmt).scalars().first()

    def get_codes(self, user_id: Optional[str] = None, market_type: Optional[str] = None) -> List[str]:
        """Return stock codes in the watch list, optionally filtered by market type."""
        with self.db.get_session() as session:
            stmt = select(WatchListItem.code)
            if user_id is not None:
                stmt = stmt.where(WatchListItem.user_id == user_id)
            if market_type is not None:
                stmt = stmt.where(WatchListItem.market_type == normalize_market_type(market_type))
            return list(session.execute(stmt).scalars().all())

    # ── Write ─────────────────────────────────────────────────────────────────

    def create(
        self,
        *,
        user_id: str,
        code: str,
        name: Optional[str] = None,
        notes: Optional[str] = None,
        is_favorite: bool = False,
        market_type: Optional[str] = None,
    ) -> WatchListItem:
        item = WatchListItem(
            user_id=user_id,
            code=code.upper().strip(),
            name=(name or "").strip() or None,
            notes=(notes or "").strip() or None,
            market_type=normalize_market_type(market_type, code),
            is_favorite=is_favorite,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        def _write(session: Session) -> WatchListItem:
            session.add(item)
            session.flush()
            session.refresh(item)
            return item

        return self.db._run_write_transaction("watch_list.create", _write)

    def update(
        self,
        item_id: int,
        *,
        user_id: Optional[str] = None,
        name: Optional[str] = None,
        notes: Optional[str] = None,
        is_favorite: Optional[bool] = None,
        market_type: Optional[str] = None,
    ) -> Optional[WatchListItem]:
        def _write(session: Session) -> Optional[WatchListItem]:
            obj = session.get(WatchListItem, item_id)
            if obj is None:
                return None
            if user_id is not None and obj.user_id != user_id:
                return None
            if name is not None:
                obj.name = name.strip() or None
            if notes is not None:
                obj.notes = notes.strip() or None
            if is_favorite is not None:
                obj.is_favorite = is_favorite
            if market_type is not None:
                obj.market_type = normalize_market_type(market_type, obj.code)
            obj.updated_at = datetime.now()
            session.flush()
            session.refresh(obj)
            return obj

        return self.db._run_write_transaction("watch_list.update", _write)

    def delete(self, item_id: int, user_id: Optional[str] = None) -> bool:
        def _write(session: Session) -> bool:
            obj = session.get(WatchListItem, item_id)
            if obj is None:
                return False
            if user_id is not None and obj.user_id != user_id:
                return False
            session.delete(obj)
            return True

        return self.db._run_write_transaction("watch_list.delete", _write)


def get_watch_list_codes(user_id: Optional[str] = None) -> List[str]:
    """读取数据库 ``watch_list`` 表中的自选股代码列表。

    取代旧的 ``config.stock_list`` 配置：分析任务、Bot 命令等所有需要"自选股"
    的场景都应通过此函数从 DB 获取，保证与 WebUI 维护的自选股一致。

    Args:
        user_id: 可选，按用户隔离；不传则返回所有用户的自选股代码（用于
            后台调度等无用户上下文的场景）。
    """
    return WatchListRepo().get_codes(user_id=user_id)


def get_watch_list_codes_by_market(market_type: str, user_id: Optional[str] = None) -> List[str]:
    """读取指定市场的自选股代码列表。"""
    return WatchListRepo().get_codes(user_id=user_id, market_type=market_type)
