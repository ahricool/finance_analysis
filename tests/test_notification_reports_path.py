# -*- coding: utf-8 -*-
"""Tests for report file save path resolution."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from finance_analysis.notification.service import NotificationService


@pytest.fixture
def reports_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reports = tmp_path / "reports"
    monkeypatch.setenv("REPORTS_DIR", str(reports))
    yield reports
    monkeypatch.delenv("REPORTS_DIR", raising=False)


def test_save_report_to_file_writes_under_configured_reports_dir(reports_dir: Path) -> None:
    service = NotificationService()
    saved_path = service.save_report_to_file("hello report", filename="unit_test_report.md")

    expected = reports_dir / "unit_test_report.md"
    assert saved_path == str(expected)
    assert expected.is_file()
    assert expected.read_text(encoding="utf-8") == "hello report"
