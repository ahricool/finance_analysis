from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

from finance_analysis.quant.data import DailyBarLoader
from finance_analysis.quant.datasets.artifact_store import ArtifactStore
from finance_analysis.quant.datasets.exporter import QlibDatasetExporter
from finance_analysis.quant.features.daily import build_daily_features
from finance_analysis.tasks.celery.jobs.quant_dataset import tasks as dataset_tasks
from qlib_worker.price_modes import require_forward_adjusted_manifest


def _row(code: str, day: date, close: float, *, open_price: float | None = None) -> dict:
    open_price = close if open_price is None else open_price
    return {
        "instrument": code, "datetime": day, "open": open_price,
        "high": max(open_price, close) + 1.0, "low": min(open_price, close) - 1.0,
        "close": close, "volume": 100.0, "amount": 9_800.0, "vwap": close,
        "vwap_source": "provider", "vwap_quality": "provider", "daily_data_source": "fixture",
    }


class BarRepository:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def load_daily_bar_rows(self, market, codes, start, end):
        return [row for row in self.rows if row["instrument"] in codes and start <= row["datetime"] <= end]


def test_loader_returns_stored_forward_adjusted_prices_without_second_adjustment() -> None:
    day = date(2026, 7, 17)
    result = DailyBarLoader(BarRepository([_row("AAPL.US", day, 50.0)])).load(
        "US", {"AAPL.US"}, day, day
    )

    assert result.frame.iloc[0][["open", "high", "low", "close", "vwap"]].to_dict() == {
        "open": 50.0, "high": 51.0, "low": 49.0, "close": 50.0, "vwap": 50.0,
    }
    assert result.frame.iloc[0]["volume"] == 100.0
    assert "forward_adjustment_factor" not in result.frame.columns


def test_forward_adjusted_company_action_series_does_not_create_false_returns() -> None:
    days = [date(2026, 7, 15), date(2026, 7, 16), date(2026, 7, 17)]
    frame = DailyBarLoader(BarRepository([_row("AAPL.US", day, 50.0) for day in days])).load(
        "US", {"AAPL.US"}, days[0], days[-1]
    ).frame
    features = build_daily_features(frame.rename(columns={"datetime": "date"}))

    assert features.iloc[-1]["ret_1d"] == 0.0


class ExportRepository(BarRepository):
    def __init__(self, rows: list[dict]):
        super().__init__(rows)
        self.snapshots: dict[int, SimpleNamespace] = {}
        self.next_id = 1

    def get_universe(self, _key):
        return SimpleNamespace(id=1, key="us_sp500", market="US", enabled=True, benchmark_code="QQQ.US")

    def create_dataset(self, values):
        snapshot = SimpleNamespace(id=self.next_id, **values, artifact_uri=None, row_count=0, symbol_count=0)
        self.snapshots[self.next_id] = snapshot
        self.next_id += 1
        return snapshot

    def update_dataset(self, snapshot_id, **values):
        for key, value in values.items():
            setattr(self.snapshots[snapshot_id], key, value)

    def get_dataset(self, snapshot_id):
        return self.snapshots[snapshot_id]

    def get_dataset_by_key(self, dataset_key):
        return next((item for item in self.snapshots.values() if item.dataset_key == dataset_key), None)


def test_dataset_export_uses_stored_prices_and_neutral_qlib_factor(tmp_path: Path) -> None:
    day = date(2026, 7, 17)
    codes = ("AAPL.US", "QQQ.US", "SPY.US", "SOXX.US")
    repository = ExportRepository([_row(code, day, 50.0) for code in codes])
    snapshot = QlibDatasetExporter(repository, ArtifactStore(tmp_path)).export(
        "US", "us_sp500", day, day, candidate_codes={"AAPL.US"}
    )
    root = tmp_path / snapshot.artifact_uri.removeprefix("quant://")
    manifest = json.loads((root / "manifest.json").read_text())
    daily = pd.read_csv(root / "source" / "daily.csv")
    factor_bin = np.fromfile(root / "features" / "aapl.us" / "factor.day.bin", dtype="<f4")

    assert manifest["daily_price_semantics"] == "forward_adjusted"
    assert manifest["price_mode"] == "forward_adjusted"
    assert require_forward_adjusted_manifest(manifest) == "forward_adjusted"
    assert "adjustment_coverage" not in manifest
    assert set(daily["close"]) == {50.0}
    assert factor_bin.tolist() == [0.0, 1.0]


def test_dataset_export_reuses_ready_snapshot_for_same_source_revision(tmp_path: Path) -> None:
    day = date(2026, 7, 17)
    codes = ("AAPL.US", "QQQ.US", "SPY.US")
    repository = ExportRepository([_row(code, day, 50.0) for code in codes])
    exporter = QlibDatasetExporter(repository, ArtifactStore(tmp_path))
    first = exporter.export("US", "us_sp500", day, day, candidate_codes={"AAPL.US"})
    second = exporter.export("US", "us_sp500", day, day, candidate_codes={"AAPL.US"})

    assert first.id == second.id
    assert repository.next_id == 2


def test_quant_dataset_task_has_no_price_mode_contract() -> None:
    snapshot = SimpleNamespace(id=7, dataset_key="adjusted-dataset", status="ready", row_count=100, symbol_count=4)
    with patch.object(dataset_tasks, "QlibDatasetExporter") as exporter_class:
        exporter_class.return_value.export.return_value = snapshot
        result = dataset_tasks.build_quant_dataset.run(
            market="US", universe="us_sp500", date_from="2025-01-01", date_to="2026-01-01"
        )

    assert "price_mode" not in exporter_class.return_value.export.call_args.kwargs
    assert "price_mode" not in result
