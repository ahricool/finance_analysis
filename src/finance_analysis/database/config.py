# -*- coding: utf-8 -*-
"""Database-owned configuration and validation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from finance_analysis.config.env_parsing import env_str


@dataclass
class DatabaseConfig:
    database_url: str = ""
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
        redis_url=env_str("REDIS_URL", "redis://localhost:6379/0") or "redis://localhost:6379/0",
    )
