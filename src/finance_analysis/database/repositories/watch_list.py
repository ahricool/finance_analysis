# -*- coding: utf-8 -*-
"""Repository for watch_list (自选股) CRUD operations."""

from __future__ import annotations

import logging
from typing import Any, Iterable, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from finance_analysis.stocks.markets import canonical_watch_list_code, normalize_market_type
from finance_analysis.database.session import DatabaseManager
from finance_analysis.database.models import WatchListItem
from finance_analysis.database.models.watch_list import WatchListTag, watch_list_tag_link
from finance_analysis.core.time import utc_now


logger = logging.getLogger(__name__)


class WatchListCodes(list[str]):
    """List-compatible valid codes with visible per-row input failures for batch jobs."""

    def __init__(self, codes: Iterable[str] = (), *, validation_failures: Optional[List[dict[str, Any]]] = None):
        super().__init__(codes)
        self.validation_failures = list(validation_failures or [])


def get_db() -> DatabaseManager:
    return DatabaseManager.get_instance()


def normalize_tag_name(name: str) -> tuple[str, str]:
    name = name.strip()
    if not 1 <= len(name) <= 32:
        raise ValueError("标签名称须为 1–32 个字符")
    return name, name.casefold()


class WatchListRepo:
    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or get_db()

    # ── Read ──────────────────────────────────────────────────────────────────

    def list_all(
        self, uid: Optional[int] = None, *, market_type: Optional[str] = None,
        tag_id: Optional[int] = None, ungrouped: bool = False,
    ) -> List[WatchListItem]:
        with self.db.get_session() as session:
            stmt = select(WatchListItem).options(selectinload(WatchListItem.tags)).order_by(WatchListItem.created_at)
            if uid is not None:
                stmt = stmt.where(WatchListItem.uid == uid)
            if market_type is not None:
                stmt = stmt.where(WatchListItem.market_type == normalize_market_type(market_type))
            if tag_id is not None:
                stmt = stmt.where(WatchListItem.tags.any(WatchListTag.id == tag_id))
            if ungrouped:
                stmt = stmt.where(~WatchListItem.tags.any())
            return session.execute(stmt).scalars().all()

    def count(self, *, uid: int, market_type: Optional[str] = None) -> int:
        with self.db.get_session() as session:
            stmt = select(func.count()).select_from(WatchListItem).where(WatchListItem.uid == uid)
            if market_type is not None:
                stmt = stmt.where(WatchListItem.market_type == normalize_market_type(market_type))
            return session.scalar(stmt)

    def get_by_id(self, item_id: int, uid: Optional[int] = None) -> Optional[WatchListItem]:
        with self.db.get_session() as session:
            obj = session.get(WatchListItem, item_id, options=[selectinload(WatchListItem.tags)])
            if obj is None:
                return None
            if uid is not None and obj.uid != uid:
                return None
            return obj

    def get_by_code(
        self,
        code: str,
        uid: Optional[int] = None,
        market_type: Optional[str] = None,
    ) -> Optional[WatchListItem]:
        with self.db.get_session() as session:
            stmt = select(WatchListItem).where(WatchListItem.code == code.upper())
            if uid is not None:
                stmt = stmt.where(WatchListItem.uid == uid)
            if market_type is not None:
                stmt = stmt.where(WatchListItem.market_type == normalize_market_type(market_type, code))
            return session.execute(stmt).scalars().first()

    def get_codes(self, uid: Optional[int] = None, market_type: Optional[str] = None) -> List[str]:
        """Return canonical business identifiers using each row's explicit market."""
        with self.db.get_session() as session:
            stmt = select(WatchListItem.id, WatchListItem.code, WatchListItem.market_type)
            if uid is not None:
                stmt = stmt.where(WatchListItem.uid == uid)
            if market_type:
                stmt = stmt.where(WatchListItem.market_type == normalize_market_type(market_type))
            codes = WatchListCodes()
            for item_id, code, market in session.execute(stmt).all():
                try:
                    codes.append(canonical_watch_list_code(code, market))
                except ValueError as exc:
                    failure = {"watch_list_id": item_id, "code": code, "market_type": market, "error": str(exc)}
                    codes.validation_failures.append(failure)
                    logger.warning("自选股校验失败 item_id=%s: %s", item_id, exc)
            return codes

    # ── Write ─────────────────────────────────────────────────────────────────

    def list_tags(self, *, uid: int) -> list[WatchListTag]:
        with self.db.get_session() as session:
            return list(session.scalars(select(WatchListTag).where(WatchListTag.uid == uid).order_by(WatchListTag.id)))

    def _create_tag(self, session: Session, *, uid: int, name: str) -> WatchListTag:
        name, key = normalize_tag_name(name)
        if session.scalar(select(WatchListTag.id).where(WatchListTag.uid == uid, WatchListTag.name_key == key)):
            raise ValueError("同名标签已存在")
        tag = WatchListTag(uid=uid, name=name, name_key=key)
        session.add(tag)
        session.flush()
        return tag

    def create_tag(self, *, uid: int, name: str) -> WatchListTag:
        def _write(session: Session) -> WatchListTag:
            tag = self._create_tag(session, uid=uid, name=name)
            session.expunge(tag)
            return tag
        return self.db._run_write_transaction("watch_list.create_tag", _write)

    def rename_tag(self, tag_id: int, *, uid: int, name: str) -> Optional[WatchListTag]:
        name, key = normalize_tag_name(name)

        def _write(session: Session) -> Optional[WatchListTag]:
            tag = session.scalar(select(WatchListTag).where(WatchListTag.id == tag_id, WatchListTag.uid == uid))
            if tag is None:
                return None
            duplicate = session.scalar(select(WatchListTag.id).where(
                WatchListTag.uid == uid, WatchListTag.name_key == key, WatchListTag.id != tag_id,
            ))
            if duplicate:
                raise ValueError("同名标签已存在")
            tag.name, tag.name_key = name, key
            session.flush()
            session.expunge(tag)
            return tag
        return self.db._run_write_transaction("watch_list.rename_tag", _write)

    def delete_tag(self, tag_id: int, *, uid: int) -> bool:
        def _write(session: Session) -> bool:
            tag = session.scalar(select(WatchListTag).where(WatchListTag.id == tag_id, WatchListTag.uid == uid))
            if tag is None:
                return False
            session.execute(watch_list_tag_link.delete().where(watch_list_tag_link.c.tag_id == tag_id))
            session.delete(tag)
            return True
        return self.db._run_write_transaction("watch_list.delete_tag", _write)

    def _resolve_tags(self, session: Session, *, uid: int, tags: list[dict]) -> list[WatchListTag]:
        resolved = {}
        for value in tags:
            if value.get("id") is not None:
                tag = session.scalar(select(WatchListTag).where(
                    WatchListTag.id == value["id"], WatchListTag.uid == uid,
                ))
                if tag is None:
                    raise ValueError("标签不存在或无权使用")
            else:
                name, key = normalize_tag_name(value["name"])
                tag = session.scalar(select(WatchListTag).where(
                    WatchListTag.uid == uid, WatchListTag.name_key == key,
                ))
                if tag is None:
                    tag = self._create_tag(session, uid=uid, name=name)
            resolved[tag.id] = tag
        return list(resolved.values())

    def create(
        self,
        *,
        uid: int,
        code: str,
        name: Optional[str] = None,
        notes: Optional[str] = None,
        market_type: Optional[str] = None,
        is_favorite: bool = False,
        tags: Optional[list[dict]] = None,
    ) -> WatchListItem:
        resolved_market = normalize_market_type(market_type, code)
        canonical_watch_list_code(code, resolved_market)  # Validate before entering the write transaction.
        item = WatchListItem(
            uid=uid,
            code=code.upper().strip(),
            name=(name or "").strip() or None,
            notes=(notes or "").strip() or None,
            market_type=resolved_market,
            is_favorite=bool(is_favorite),
            created_at=utc_now(),
            updated_at=utc_now(),
        )

        def _write(session: Session) -> WatchListItem:
            item.tags = self._resolve_tags(session, uid=uid, tags=tags) if tags else []
            session.add(item)
            session.flush()
            session.refresh(item)
            for tag in item.tags:
                session.expunge(tag)  # Commit must not expire nested response objects.
            session.expunge(item)
            return item

        return self.db._run_write_transaction("watch_list.create", _write)

    def update(
        self,
        item_id: int,
        *,
        uid: Optional[int] = None,
        name: Optional[str] = None,
        notes: Optional[str] = None,
        market_type: Optional[str] = None,
        is_favorite: Optional[bool] = None,
        tags: Optional[list[dict]] = None,
    ) -> Optional[WatchListItem]:
        def _write(session: Session) -> Optional[WatchListItem]:
            obj = session.get(WatchListItem, item_id)
            if obj is None:
                return None
            if uid is not None and obj.uid != uid:
                return None
            resolved_market = normalize_market_type(market_type, obj.code) if market_type is not None else obj.market_type
            # Validate before mutating any row fields.
            canonical_watch_list_code(obj.code, resolved_market)
            if tags is not None:
                obj.tags = self._resolve_tags(session, uid=obj.uid, tags=tags)
            if name is not None:
                obj.name = name.strip() or None
            if notes is not None:
                obj.notes = notes.strip() or None
            if market_type is not None:
                obj.market_type = resolved_market
            if is_favorite is not None:
                obj.is_favorite = bool(is_favorite)
            obj.updated_at = utc_now()
            session.flush()
            session.refresh(obj)
            for tag in obj.tags:
                session.expunge(tag)
            session.expunge(obj)
            return obj

        return self.db._run_write_transaction("watch_list.update", _write)

    def delete(self, item_id: int, uid: Optional[int] = None) -> bool:
        def _write(session: Session) -> bool:
            obj = session.get(WatchListItem, item_id)
            if obj is None:
                return False
            if uid is not None and obj.uid != uid:
                return False
            session.delete(obj)
            return True

        return self.db._run_write_transaction("watch_list.delete", _write)


def get_watch_list_codes(uid: Optional[int] = None) -> List[str]:
    """读取数据库 ``watch_list`` 表中的自选股代码列表。

    取代旧的 ``config.stock_list`` 配置：分析任务、Bot 命令等所有需要"自选股"
    的场景都应通过此函数从 DB 获取，保证与 WebUI 维护的自选股一致。

    Args:
        uid: 可选，按用户隔离；不传则返回所有用户的自选股代码（用于
            后台调度等无用户上下文的场景）。
    """
    return WatchListRepo().get_codes(uid=uid)


def get_watch_list_codes_by_market(market_type: str, uid: Optional[int] = None) -> List[str]:
    """读取指定市场的自选股代码列表。"""
    return WatchListRepo().get_codes(uid=uid, market_type=market_type)
