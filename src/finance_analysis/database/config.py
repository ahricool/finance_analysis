# -*- coding: utf-8 -*-
"""Database-owned configuration and validation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from finance_analysis.config.env_parsing import env_int, env_str


@dataclass(frozen=True)
class DatabaseConfig:
    database_url: str = ""
    data_dir: str = "./data"
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_pool_recycle: int = 1800
    redis_url: str = "redis://localhost:6379/0"

    def get_db_url(self) -> str:
        url = (self.database_url or "").strip()
        if not url:
            raise ValueError(
                "未配置 DATABASE_URL。本项目仅支持 PostgreSQL，请在环境变量中设置 "
                "DATABASE_URL（例如 postgresql+psycopg2://user:pass@host:5432/dbname）。"
            )
        if not url.lower().startswith("postgresql"):
            raise ValueError("DATABASE_URL 必须是 PostgreSQL 连接串（以 postgresql:// 或 postgresql+... 开头）。")
        return url

    def validate(self) -> list[str]:
        try:
            self.get_db_url()
        except ValueError as exc:
            return [str(exc)]
        return []


@lru_cache(maxsize=1)
def get_database_config() -> DatabaseConfig:
    return DatabaseConfig(
        database_url=env_str("DATABASE_URL", "") or "",
        data_dir=env_str("DATA_DIR", "./data") or "./data",
        db_pool_size=env_int("DB_POOL_SIZE", 10, minimum=1),
        db_max_overflow=env_int("DB_MAX_OVERFLOW", 5, minimum=0),
        db_pool_recycle=env_int("DB_POOL_RECYCLE", 1800, minimum=0),
        redis_url=env_str("REDIS_URL", "redis://localhost:6379/0") or "redis://localhost:6379/0",
    )
