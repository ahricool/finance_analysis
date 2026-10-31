# -*- coding: utf-8 -*-
"""Database manager, engine, session factory, and storage access methods."""

import atexit
from contextlib import contextmanager
import logging
from typing import Callable, Optional, TypeVar

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from finance_analysis.database.config import get_database_config
from finance_analysis.database.bootstrap import bootstrap_database
from finance_analysis.database.repositories.llm_usage import LLMUsageMixin

logger = logging.getLogger(__name__)
T = TypeVar("T")


class DatabaseManager(LLMUsageMixin):
    """
    数据库管理器 - 单例模式

    职责：
    1. 管理数据库连接池
    2. 提供 Session 上下文管理
    3. 封装数据存取操作
    """

    _instance: Optional["DatabaseManager"] = None
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
        if getattr(self, "_initialized", False):
            return

        config = get_database_config()
        if db_url is None:
            db_url = config.get_db_url()

        self._db_url = db_url

        backend = str(db_url).split(":")[0].split("+")[0].lower()
        is_pg = backend == "postgresql"
        if not is_pg:
            raise ValueError(
                "仅支持 PostgreSQL。请使用 postgresql:// 或 postgresql+psycopg2:// 等 URL；" f"当前为: {db_url!r}"
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
    def get_instance(cls) -> "DatabaseManager":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        elif not getattr(cls._instance, "_initialized", False):
            cls._instance.__init__()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（用于测试）"""
        if cls._instance is not None:
            if hasattr(cls._instance, "_engine") and cls._instance._engine is not None:
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
        if not getattr(self, "_initialized", False) or not hasattr(self, "_SessionLocal"):
            raise RuntimeError("DatabaseManager 未正确初始化。" "请确保通过 DatabaseManager.get_instance() 获取实例。")
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

        if not getattr(self, "_initialized", False) or not hasattr(self, "_engine"):
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


# 便捷函数
def get_db() -> DatabaseManager:
    """获取数据库管理器实例的快捷方式"""
    return DatabaseManager.get_instance()
