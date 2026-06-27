# -*- coding: utf-8 -*-
"""Tests for unified project and runtime data path helpers."""

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
    clear_paths_cache,
    ensure_data_directories,
    get_data_dir,
    get_env_file_path,
    get_log_app_dir,
    get_log_dir,
    get_report_analysis_dir,
    get_reports_dir,
    get_runtime_locks_dir,
    resolve_project_path,
)


@pytest.fixture(autouse=True)
def _reset_paths_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATA_DIR", raising=False)
    clear_paths_cache()
    yield
    clear_paths_cache()


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


def test_get_data_dir_default() -> None:
    assert get_data_dir() == (PROJECT_ROOT / "data").resolve()


def test_get_data_dir_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom = tmp_path / "runtime-root"
    monkeypatch.setenv("DATA_DIR", str(custom))
    clear_paths_cache()
    assert get_data_dir() == custom.resolve()


def test_get_data_dir_independent_of_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom = tmp_path / "outside-data"
    monkeypatch.setenv("DATA_DIR", str(custom))
    clear_paths_cache()
    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        assert get_data_dir() == custom.resolve()
    finally:
        os.chdir(original)


def test_derived_directories_under_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data-root"))
    clear_paths_cache()

    assert get_log_dir() == (tmp_path / "data-root" / "logs").resolve()
    assert get_log_app_dir() == (tmp_path / "data-root" / "logs" / "app").resolve()
    assert get_report_analysis_dir() == (tmp_path / "data-root" / "reports" / "analysis").resolve()
    assert get_runtime_locks_dir() == (tmp_path / "data-root" / "runtime" / "locks").resolve()


def test_get_reports_dir_points_to_analysis_subdirectory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    clear_paths_cache()
    assert get_reports_dir() == get_report_analysis_dir()


def test_ensure_data_directories_creates_layout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    clear_paths_cache()

    ensure_data_directories()
    ensure_data_directories()

    root = tmp_path / "data"
    assert root.is_dir()
    assert (root / "logs" / "app").is_dir()
    assert (root / "logs" / "celery").is_dir()
    assert (root / "logs" / "scheduler").is_dir()
    assert (root / "logs" / "access").is_dir()
    assert (root / "reports" / "analysis").is_dir()
    assert (root / "reports" / "exports").is_dir()
    assert (root / "reports" / "assets").is_dir()
    assert (root / "uploads" / "avatars").is_dir()
    assert (root / "cache").is_dir()
    assert (root / "tmp").is_dir()
    assert (root / "runtime" / "locks").is_dir()
    assert (root / "runtime" / "pid").is_dir()
    assert (root / "backups").is_dir()


def test_runtime_paths_do_not_use_project_root_logs_or_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    clear_paths_cache()
    ensure_data_directories()

    log_root = get_log_dir()
    report_root = get_report_analysis_dir()
    assert log_root.is_relative_to(get_data_dir())
    assert report_root.is_relative_to(get_data_dir())
    assert log_root != PROJECT_ROOT / "logs"
    assert report_root != PROJECT_ROOT / "reports"


def test_repo_root_alias_matches_project_root() -> None:
    assert paths_module.repo_root() == PROJECT_ROOT
