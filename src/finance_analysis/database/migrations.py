# -*- coding: utf-8 -*-
"""Apply Alembic migrations from application code or tooling."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from finance_analysis.core.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)


def run_alembic_upgrade_head(project_root: Optional[Path] = None) -> None:
    """Run ``alembic upgrade head`` using ``alembic.ini`` next to the project root.

    Args:
        project_root: Repository root (directory containing ``alembic.ini``).
            Defaults to the parent of the ``src/`` package.
    """
    from alembic import command
    from alembic.config import Config as AlembicConfig

    root = project_root or PROJECT_ROOT
    ini_path = root / "alembic.ini"
    if not ini_path.is_file():
        raise FileNotFoundError(
            f"Alembic 配置文件不存在: {ini_path}。请确认仓库根目录包含 alembic.ini。"
        )

    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(root))
    cfg.set_main_option("version_path_separator", "os")
    logger.info("正在执行数据库迁移: alembic upgrade head")
    command.upgrade(cfg, "head")
    logger.info("数据库迁移已完成")
