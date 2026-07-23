from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from finance_analysis.quant.datasets.exporter import QlibDatasetExporter
from finance_analysis.quant.data import DailyBarLoader
from finance_analysis.tasks.celery.schedule import QUEUE_QLIB, build_task_routes


ROOT = Path(__file__).resolve().parents[1]


def test_main_environment_does_not_install_qlib() -> None:
    assert importlib.util.find_spec("qlib") is None


def test_vwap_prefers_database_values_and_reports_hlc3_fallback_ratio() -> None:
    frame = pd.DataFrame(
        {
            "low": [9.0, 19.0, 29.0, np.nan],
            "high": [11.0, 21.0, 31.0, np.nan],
            "close": [10.0, 20.0, 30.0, np.nan],
            "volume": [100.0, 100.0, 100.0, 0.0],
            "amount": [1_000.0, np.nan, np.nan, np.nan],
            "vwap": [10.25, 20.5, np.nan, np.nan],
            "vwap_quality": ["calculated", "estimated", None, "missing"],
        }
    )
    result, report = DailyBarLoader._with_raw_vwap(frame)
    assert result.loc[0, "vwap"] == 10.25
    assert result.loc[1, "vwap"] == 20.5
    assert result.loc[2, "vwap"] == 30.0
    assert np.isnan(result.loc[3, "vwap"])
    assert report == {
        "valid_rows": 3,
        "provider_calculated_rows": 1,
        "estimated_rows": 2,
        "missing_rows": 1,
        "provider_calculated_ratio": 0.25,
        "estimated_ratio": 0.5,
        "missing_ratio": 0.25,
    }
    assert "vwap" in QlibDatasetExporter.FIELDS


def test_qlib_writer_exports_persisted_vwap_field(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "instrument": ["AAPL.US"],
        "datetime": [pd.Timestamp("2026-07-17")],
        "open": [10.0],
        "high": [11.0],
        "low": [9.0],
        "close": [10.5],
        "volume": [100.0],
        "amount": [np.nan],
        "forward_adjustment_factor": [1.0],
        "vwap": [10.25],
        "vwap_source": ["hlc3"],
        "vwap_quality": ["estimated"],
    })
    exporter = object.__new__(QlibDatasetExporter)
    exporter._write_qlib(tmp_path, frame)
    values = np.fromfile(tmp_path / "features" / "aapl.us" / "vwap.day.bin", dtype="<f4")
    assert values.tolist() == pytest.approx([0.0, 10.25])


def test_qlib_tasks_have_explicit_queue_routes() -> None:
    routes = build_task_routes()
    assert QUEUE_QLIB == "qlib"
    assert routes["qlib.model.train"]["queue"] == QUEUE_QLIB
    assert routes["qlib.model.predict"]["queue"] == QUEUE_QLIB


def test_main_workers_do_not_consume_qlib_queue() -> None:
    for filename in ("docker-compose.dev.yml", "docker-compose.prod.yml"):
        compose = yaml.safe_load((ROOT / filename).read_text(encoding="utf-8"))
        command = " ".join(compose["services"]["worker"]["command"])
        assert "celery,alerts,analysis,ingestion,maintenance" in command
        assert "qlib" not in command
        qlib_service = compose["services"]["qlib-worker"]
        assert "DATABASE_URL" not in qlib_service.get("environment", {})
        assert "QLIB_WORKER_URL" not in qlib_service.get("environment", {})


def test_no_http_sidecar_or_blocking_qlib_wait_remains() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "finance_analysis").rglob("*.py")
    )
    assert "QLIB_WORKER_URL" not in source
    assert "QlibAdapter" not in source
    quant_tasks = (
        ROOT / "src" / "finance_analysis" / "tasks" / "celery" / "jobs" / "quant_training" / "tasks.py"
    ).read_text(encoding="utf-8")
    assert ".get(" not in quant_tasks
    assert "httpx" not in quant_tasks
