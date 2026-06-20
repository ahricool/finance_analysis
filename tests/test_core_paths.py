# -*- coding: utf-8 -*-
"""Tests for unified project path helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from finance_analysis.core import paths as paths_module
from finance_analysis.core.paths import (
    PROJECT_ROOT,
    SOURCE_ROOT,
    STATIC_DIR,
    STRATEGIES_DIR,
    TEMPLATES_DIR,
    WEB_DIR,
    get_env_file_path,
    get_reports_dir,
    resolve_project_path,
)


def test_project_root_layout() -> None:
    assert (PROJECT_ROOT / "pyproject.toml").is_file()
    assert (PROJECT_ROOT / "src").is_dir()
    assert (PROJECT_ROOT / "src" / "finance_analysis").is_dir()
    assert SOURCE_ROOT == PROJECT_ROOT / "src"


def test_standard_resource_directories() -> None:
    assert WEB_DIR == PROJECT_ROOT / "web"
    assert STATIC_DIR == PROJECT_ROOT / "static"
    assert TEMPLATES_DIR == PROJECT_ROOT / "templates"
    assert STRATEGIES_DIR == PROJECT_ROOT / "strategies"


def test_resolve_project_path() -> None:
    assert resolve_project_path("alembic.ini") == PROJECT_ROOT / "alembic.ini"


def test_get_env_file_path_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENV_FILE", raising=False)
    assert get_env_file_path() == PROJECT_ROOT / ".env"


def test_get_env_file_path_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom = tmp_path / "custom.env"
    custom.write_text("FOO=bar\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(custom))
    assert get_env_file_path() == custom.resolve()


def test_get_reports_dir_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REPORTS_DIR", raising=False)
    assert get_reports_dir() == PROJECT_ROOT / "reports"


def test_get_reports_dir_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reports = tmp_path / "saved-reports"
    monkeypatch.setenv("REPORTS_DIR", str(reports))
    assert get_reports_dir() == reports.resolve()


def test_repo_root_alias_matches_project_root() -> None:
    assert paths_module.repo_root() == PROJECT_ROOT
