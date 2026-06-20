# -*- coding: utf-8 -*-
"""Repository path helpers — single source of truth for project layout paths."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PACKAGE_ROOT.parent
PROJECT_ROOT = SOURCE_ROOT.parent

STATIC_DIR = PROJECT_ROOT / "static"
WEB_DIR = PROJECT_ROOT / "web"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"


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
    """Return the directory used for saved report files."""
    configured = os.getenv("REPORTS_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return PROJECT_ROOT / "reports"


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
    "get_env_file_path",
    "get_reports_dir",
    "repo_root",
    "resolve_project_path",
]
