# -*- coding: utf-8 -*-
"""Tests for report file save path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from finance_analysis.core.paths import clear_paths_cache, get_report_analysis_dir
from finance_analysis.notification.service import NotificationService


@pytest.fixture()
def reports_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_root))
    clear_paths_cache()
    yield get_report_analysis_dir()
    clear_paths_cache()


def test_save_report_to_file_writes_under_configured_reports_dir(reports_dir: Path) -> None:
    service = NotificationService()
    saved_path = service.save_report_to_file("hello report", filename="unit_test_report.md")

    expected = reports_dir / "unit_test_report.md"
    assert Path(saved_path) == expected
    assert expected.read_text(encoding="utf-8") == "hello report"
