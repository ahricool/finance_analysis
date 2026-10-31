# -*- coding: utf-8 -*-
"""Database manager, engine, session factory, and storage access methods."""

import atexit
from contextlib import contextmanager
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING, TypeVar

from sqlalchemy import and_, create_engine, desc, event, select
from sqlalchemy.orm import Session, sessionmaker

from finance_analysis.database.config import get_database_config
from finance_analysis.database.base import ensure_aware_datetime
from finance_analysis.database.bootstrap import bootstrap_database
from finance_analysis.database.models import (
    NewsIntel,
    NewsIntelUsage,
)
from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.llm_usage import LLMUsageMixin
from finance_analysis.database.repositories.news_time import effective_news_time

logger = logging.getLogger(__name__)
T = TypeVar("T")

if TYPE_CHECKING:
    from finance_analysis.database.news import NewsItem


class DatabaseManager(LLMUsageMixin):
    """
    数据库管理器 - 单例模式

    职责：
    1. 管理数据库连接池
    2. 提供 Session 上下文管理
    3. 封装数据存取操作
    """

    _instance: Optional['DatabaseManager'] = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):
        """单例模式实现"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_url: Optional[str] = None):
        """
        初始化数据库管理器

        Args:
            db_url: 数据库连接 URL（可选，默认从配置读取）
        """
        if getattr(self, '_initialized', False):
            return

        config = get_database_config()
        if db_url is None:
            db_url = config.get_db_url()

        self._db_url = db_url

        backend = str(db_url).split(":")[0].split("+")[0].lower()
        is_pg = backend == "postgresql"
        if not is_pg:
            raise ValueError(
                "仅支持 PostgreSQL。请使用 postgresql:// 或 postgresql+psycopg2:// 等 URL；"
                f"当前为: {db_url!r}"
            )

        engine_kwargs: dict = {
            "echo": False,
            "pool_pre_ping": True,
            "pool_size": config.db_pool_size,
            "max_overflow": config.db_max_overflow,
            "pool_recycle": config.db_pool_recycle,
        }

        # 创建数据库引擎
        self._engine = create_engine(
            db_url,
            **engine_kwargs,
        )
        event.listen(self._engine, "connect", self._set_utc_timezone)

        # 创建 Session 工厂
        self._SessionLocal = sessionmaker(
            bind=self._engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )

        # 数据库结构：Alembic 迁移（替代 create_all）+ 启动初始化
        bootstrap_database(self)

        logger.info(f"数据库初始化完成: {db_url}")

        # 注册退出钩子，确保程序退出时关闭数据库连接
        atexit.register(DatabaseManager._cleanup_engine, self._engine)

    @classmethod
    def get_instance(cls) -> 'DatabaseManager':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        elif not getattr(cls._instance, '_initialized', False):
            cls._instance.__init__()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（用于测试）"""
        if cls._instance is not None:
            if hasattr(cls._instance, '_engine') and cls._instance._engine is not None:
                dispose = getattr(cls._instance._engine, "dispose", None)
                if callable(dispose):
                    dispose()
            cls._instance._initialized = False
            cls._instance = None

    @classmethod
    def _cleanup_engine(cls, engine) -> None:
        """
        清理数据库引擎（atexit 钩子）

        确保程序退出时关闭所有数据库连接，避免 ResourceWarning

        Args:
            engine: SQLAlchemy 引擎对象
        """
        try:
            if engine is not None:
                dispose = getattr(engine, "dispose", None)
                if callable(dispose):
                    dispose()
                    logger.debug("数据库引擎已清理")
        except Exception as e:
            logger.warning(f"清理数据库引擎时出错: {e}")

    @staticmethod
    def _set_utc_timezone(dbapi_connection, connection_record) -> None:
        """Force PostgreSQL sessions to UTC so timestamptz I/O is stable."""
        del connection_record
        # SET inside an implicit transaction is reverted by pool rollback. Run
        # connection initialization outside a transaction so UTC survives reuse.
        previous_autocommit = dbapi_connection.autocommit
        dbapi_connection.autocommit = True
        try:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("SET TIME ZONE 'UTC'")
            finally:
                cursor.close()
        finally:
            dbapi_connection.autocommit = previous_autocommit


    def _run_write_transaction(
        self,
        operation_name: str,
        write_operation: Callable[[Session], T],
    ) -> T:
        session = self.get_session()
        try:
            result = write_operation(session)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


    def get_session(self) -> Session:
        """
        获取数据库 Session

        使用示例:
            with db.get_session() as session:
                # 执行查询
                session.commit()  # 如果需要
        """
        if not getattr(self, '_initialized', False) or not hasattr(self, '_SessionLocal'):
            raise RuntimeError(
                "DatabaseManager 未正确初始化。"
                "请确保通过 DatabaseManager.get_instance() 获取实例。"
            )
        session = self._SessionLocal()
        try:
            return session
        except Exception:
            session.close()
            raise

    def connect(self):
        """Open a raw SQLAlchemy connection owned by the caller.

        Session-scoped PostgreSQL features such as advisory locks must keep the
        same connection open for their full lifetime.
        """

        if not getattr(self, '_initialized', False) or not hasattr(self, '_engine'):
            raise RuntimeError("DatabaseManager 未正确初始化")
        return self._engine.connect()

    @contextmanager
    def session_scope(self):
        """Provide a transactional scope around a series of operations."""
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


    def save_news_intel(
        self,
        code: str,
        usage_type: str,
        items: list["NewsItem"],
        provider: str,
        query_context: Optional[Dict[str, str]] = None,
    ) -> int:
        """
        保存新闻情报到数据库

        去重策略：
        - 优先按 URL 去重（唯一约束）
        - URL 缺失时按 title + source + published_date 进行软去重

        关联策略：
        - news_intel_usage 保存 usage_type、symbol、query_id 和 uid，重复抓取不覆盖原始事实
        """
        if not items:
            return 0

        saved_count = 0
        query_ctx = query_context or {}
        current_query_id = (query_ctx.get("query_id") or "").strip()
        owner_uid = None
        raw_uid = query_ctx.get("uid")
        if raw_uid is not None and str(raw_uid).strip():
            try:
                owner_uid = int(raw_uid)
            except (TypeError, ValueError):
                owner_uid = None

        def _write(session: Session) -> int:
            local_saved_count = 0

            for item in items:
                title = (item.title or '').strip()
                url = (item.url or '').strip()
                source = (item.source or '').strip()
                snippet = (item.snippet or '').strip()
                published_date = self._parse_published_date(item.published_date)

                if not title and not url:
                    continue

                url_key = url or self._build_fallback_url_key(
                    title=title,
                    source=source,
                    published_date=published_date
                )

                from sqlalchemy.dialects.postgresql import insert as pg_insert
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert

                insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
                # Hash the complete original headline above; only the stored
                # display title is bounded by the existing VARCHAR(300) schema.
                values = dict(
                            title=title[:300],
                            snippet=snippet,
                            url=url_key,
                            source=source,
                            published_date=published_date,
                    provider=provider,
                            fetched_at=utc_now(),
                        )
                record_id = session.execute(
                    insert(NewsIntel)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["url"])
                    .returning(NewsIntel.id)
                ).scalar_one_or_none()
                if record_id is not None:
                    local_saved_count += 1
                else:
                    record_id = session.execute(select(NewsIntel.id).where(NewsIntel.url == url_key)).scalar_one()
                session.execute(
                    insert(NewsIntelUsage)
                    .values(
                        news_intel_id=record_id,
                        usage_type=usage_type or "news",
                        query_id=current_query_id,
                        symbol=code,
                        uid=owner_uid,
                        observed_at=utc_now(),
                    )
                    .on_conflict_do_update(
                        index_elements=["news_intel_id", "usage_type", "query_id", "symbol"],
                        set_={"observed_at": utc_now()},
                    )
                )

            return local_saved_count

        try:
            saved_count = self._run_write_transaction(
                f"save_news_intel[{code}]",
                _write,
            )
            logger.info(f"保存新闻情报成功: {code}, 新增 {saved_count} 条")
        except Exception as e:
            logger.exception(f"保存新闻情报失败: {e}")
            raise

        return saved_count


    def get_recent_news(self, code: str, days: int = 7, limit: int = 20) -> List[NewsIntel]:
        """
        获取指定股票最近 N 天的新闻：发布时间优先，缺失时取该股票最近观察时间。
        """
        cutoff_date = utc_now() - timedelta(days=days)
        news_time = effective_news_time(NewsIntelUsage.symbol == code)

        with self.get_session() as session:
            results = (
                session.execute(
                select(NewsIntel)
                .where(
                    and_(
                            NewsIntel.id.in_(select(NewsIntelUsage.news_intel_id).where(NewsIntelUsage.symbol == code)),
                            news_time >= cutoff_date,
                    )
                )
                .order_by(desc(news_time), desc(NewsIntel.id))
                .limit(limit)
                )
                .scalars()
                .all()
            )

            return list(results)

    def get_news_intel_by_query_id(self, query_id: str, limit: int = 20) -> List[NewsIntel]:
        """
        根据 query_id 获取新闻情报列表

        Args:
            query_id: 分析记录唯一标识
            limit: 返回数量限制

        Returns:
            NewsIntel 列表（按发布时间或该 query 最近观察时间倒序）
        """
        with self.get_session() as session:
            results = (
                session.execute(
                select(NewsIntel)
                    .where(
                        NewsIntel.id.in_(
                            select(NewsIntelUsage.news_intel_id).where(NewsIntelUsage.query_id == query_id)
                        )
                    )
                .order_by(
                        desc(effective_news_time(NewsIntelUsage.query_id == query_id)), desc(NewsIntel.id)
                )
                .limit(limit)
                )
                .scalars()
                .all()
            )

            return list(results)


    @staticmethod
    def _parse_published_date(value: Optional[Any]) -> Optional[datetime]:
        """
        解析发布时间字符串（失败返回 None）
        """
        if not value:
            return None

        parsed = ensure_aware_datetime(value)
        if parsed is not None:
            return parsed

        text = str(value).strip()
        if not text:
            return None

        # 优先尝试 ISO 格式
        try:
            return ensure_aware_datetime(datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            pass

        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y/%m/%d",
        ):
            try:
                return ensure_aware_datetime(datetime.strptime(text, fmt))
            except ValueError:
                continue

        return None


    @staticmethod
    def _build_fallback_url_key(
        title: str,
        source: str,
        published_date: Optional[datetime]
    ) -> str:
        """
        生成无 URL 时的去重键（确保稳定且较短）
        """
        date_str = published_date.isoformat() if published_date else ""
        raw_key = f"{title}|{source}|{date_str}"
        digest = hashlib.md5(raw_key.encode("utf-8")).hexdigest()
        return f"no-url:{digest}"


# 便捷函数
def get_db() -> DatabaseManager:
    """获取数据库管理器实例的快捷方式"""
    return DatabaseManager.get_instance()
