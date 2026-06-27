# -*- coding: utf-8 -*-
"""Repository and runtime data path helpers — single source of truth for layout paths."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PACKAGE_ROOT.parent
PROJECT_ROOT = SOURCE_ROOT.parent

STATIC_DIR = PROJECT_ROOT / "static"
WEB_DIR = PROJECT_ROOT / "web"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"

_RUNTIME_SUBDIRS = (
    "logs/app",
    "logs/celery",
    "logs/scheduler",
    "logs/access",
    "reports/analysis",
    "reports/exports",
    "reports/assets",
    "uploads",
    "uploads/avatars",
    "cache",
    "tmp",
    "runtime/locks",
    "runtime/pid",
    "backups",
)


def clear_paths_cache() -> None:
    """Clear cached path resolution (for tests and env reload)."""
    get_data_dir.cache_clear()


@lru_cache(maxsize=1)
def get_data_dir() -> Path:
    """Return the root directory for all runtime application data."""
    configured = os.getenv("DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (PROJECT_ROOT / "data").resolve()


def get_log_dir() -> Path:
    """Return ``data/logs``."""
    return get_data_dir() / "logs"


def get_log_app_dir() -> Path:
    """Return ``data/logs/app`` for the FastAPI / main server process."""
    return get_log_dir() / "app"


def get_log_celery_dir() -> Path:
    """Return ``data/logs/celery`` for Celery workers and task logs."""
    return get_log_dir() / "celery"


def get_log_scheduler_dir() -> Path:
    """Return ``data/logs/scheduler`` for in-process scheduled task logs."""
    return get_log_dir() / "scheduler"


def get_log_access_dir() -> Path:
    """Return ``data/logs/access`` for HTTP access logs."""
    return get_log_dir() / "access"


def get_report_dir() -> Path:
    """Return ``data/reports``."""
    return get_data_dir() / "reports"


def get_report_analysis_dir() -> Path:
    """Return ``data/reports/analysis`` for saved analysis / review reports."""
    return get_report_dir() / "analysis"


def get_report_exports_dir() -> Path:
    """Return ``data/reports/exports``."""
    return get_report_dir() / "exports"


def get_report_assets_dir() -> Path:
    """Return ``data/reports/assets``."""
    return get_report_dir() / "assets"


def get_upload_dir() -> Path:
    """Return ``data/uploads``."""
    return get_data_dir() / "uploads"


def get_avatar_upload_dir() -> Path:
    """Return ``data/uploads/avatars``."""
    return get_upload_dir() / "avatars"


def get_cache_dir() -> Path:
    """Return ``data/cache``."""
    return get_data_dir() / "cache"


def get_temp_dir() -> Path:
    """Return ``data/tmp``."""
    return get_data_dir() / "tmp"


def get_runtime_dir() -> Path:
    """Return ``data/runtime``."""
    return get_data_dir() / "runtime"


def get_runtime_locks_dir() -> Path:
    """Return ``data/runtime/locks``."""
    return get_runtime_dir() / "locks"


def get_runtime_pid_dir() -> Path:
    """Return ``data/runtime/pid``."""
    return get_runtime_dir() / "pid"


def get_backup_dir() -> Path:
    """Return ``data/backups``."""
    return get_data_dir() / "backups"


def resolve_project_path(*parts: str) -> Path:
    """Join path segments under the repository root."""
    return PROJECT_ROOT.joinpath(*parts)


def get_env_file_path() -> Path:
    """Return the active ``.env`` file path (honours ``ENV_FILE`` when set)."""
    configured = os.getenv("ENV_FILE")
    if configured:
        return Path(configured).expanduser().resolve()
    return PROJECT_ROOT / ".env"


def get_reports_dir() -> Path:
    """Return the directory used for saved report files (analysis reports)."""
    return get_report_analysis_dir()


def ensure_data_directories() -> None:
    """Create all runtime data subdirectories idempotently."""
    root = get_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    for relative in _RUNTIME_SUBDIRS:
        (root / relative).mkdir(parents=True, exist_ok=True)


def repo_root() -> Path:
    """Backward-compatible alias for :data:`PROJECT_ROOT`."""
    return PROJECT_ROOT


__all__ = [
    "PACKAGE_ROOT",
    "PROJECT_ROOT",
    "SOURCE_ROOT",
    "STATIC_DIR",
    "STRATEGIES_DIR",
    "TEMPLATES_DIR",
    "WEB_DIR",
    "clear_paths_cache",
    "ensure_data_directories",
    "get_avatar_upload_dir",
    "get_backup_dir",
    "get_cache_dir",
    "get_data_dir",
    "get_env_file_path",
    "get_log_access_dir",
    "get_log_app_dir",
    "get_log_celery_dir",
    "get_log_dir",
    "get_log_scheduler_dir",
    "get_report_analysis_dir",
    "get_report_assets_dir",
    "get_report_dir",
    "get_report_exports_dir",
    "get_reports_dir",
    "get_runtime_dir",
    "get_runtime_locks_dir",
    "get_runtime_pid_dir",
    "get_temp_dir",
    "get_upload_dir",
    "repo_root",
    "resolve_project_path",
]
