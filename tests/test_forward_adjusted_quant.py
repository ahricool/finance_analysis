from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from finance_analysis.quant.data import DailyBarLoader
from finance_analysis.quant.datasets.artifact_store import ArtifactStore
from finance_analysis.quant.datasets.exporter import QlibDatasetExporter
from finance_analysis.quant.exceptions import AdjustmentFactorMissingError, QuantDatasetMissingError
from finance_analysis.quant.features.daily import build_daily_features
from finance_analysis.quant.features.service import DailyResearchService
from finance_analysis.quant.pipeline.service import QuantTrainingPipeline
from finance_analysis.tasks.celery.jobs.quant_dataset import tasks as dataset_tasks


def _row(
    code: str,
    day: date,
    close: float,
    factor: float | None,
    *,
    open_price: float | None = None,
    amount: float = 9_800.0,
    volume: float = 100.0,
) -> dict:
    open_price = close if open_price is None else open_price
    return {
        "instrument": code,
        "datetime": day,
        "open": open_price,
        "high": max(open_price, close) + 2.0,
        "low": min(open_price, close) - 2.0,
        "close": close,
        "volume": volume,
        "amount": amount,
        "vwap": 98.0 if close == 100.0 else close,
        "vwap_source": "provider",
        "vwap_quality": "provider",
        "daily_data_source": "fixture",
        "daily_source_priority": 1,
        "forward_adjustment_factor": factor,
        "adjustment_source": "fixture-adjustment" if factor is not None else None,
        "adjustment_source_hash": f"factor-{factor}" if factor is not None else None,
    }


class BarRepository:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def load_daily_bar_rows(self, market, codes, start, end):
        return [
            row
            for row in self.rows
            if row["instrument"] in codes and start <= row["datetime"] <= end
        ]


def test_forward_adjustment_applies_price_fields_once_and_preserves_volume_amount() -> None:
    day = date(2026, 7, 17)
    raw = _row("AAPL.US", day, 100.0, 0.5)
    result = DailyBarLoader(BarRepository([raw])).load(
        "US", {"AAPL.US"}, day, day, "forward_adjusted"
    )
    bar = result.frame.iloc[0]

    assert bar[["open", "high", "low", "close", "vwap"]].to_dict() == pytest.approx(
        {"open": 50.0, "high": 51.0, "low": 49.0, "close": 50.0, "vwap": 49.0}
    )
    assert bar["volume"] == 100.0
    assert bar["amount"] == 9_800.0
    assert result.adjustment_coverage == {
        "expected_rows": 1,
        "factor_rows": 1,
        "missing_rows": 0,
        "coverage_ratio": 1.0,
        "provider_distribution": {"fixture-adjustment": 1},
    }


def test_raw_mode_remains_available_for_diagnostics_without_fake_factor() -> None:
    day = date(2026, 7, 17)
    result = DailyBarLoader(BarRepository([_row("AAPL.US", day, 100.0, None)])).load(
        "US", {"AAPL.US"}, day, day, "raw"
    )
    assert result.frame.iloc[0]["close"] == 100.0
    assert pd.isna(result.frame.iloc[0]["forward_adjustment_factor"])
    assert result.adjustment_coverage["missing_rows"] == 1


@pytest.mark.parametrize(
    ("raw_closes", "factors"),
    [
        ([100.0, 100.0, 50.0], [0.5, 0.5, 1.0]),  # one-for-two split
        ([100.0, 100.0, 99.0], [0.99, 0.99, 1.0]),  # cash-dividend ex-date gap
    ],
)
def test_company_action_gaps_do_not_create_false_returns_or_labels(
    raw_closes: list[float],
    factors: list[float],
) -> None:
    days = [date(2026, 7, 15), date(2026, 7, 16), date(2026, 7, 17)]
    rows = [_row("AAPL.US", day, close, factor) for day, close, factor in zip(days, raw_closes, factors)]
    adjusted = DailyBarLoader(BarRepository(rows)).load(
        "US", {"AAPL.US"}, days[0], days[-1], "forward_adjusted"
    ).frame
    features = build_daily_features(adjusted.rename(columns={"datetime": "date"}))

    assert features.iloc[-1]["ret_1d"] == pytest.approx(0.0)
    # This is the same exit/entry expression consumed from source/daily.csv by the Qlib target builder.
    label_return = adjusted["close"].shift(-2) / adjusted["close"].shift(-1) - 1.0
    assert label_return.iloc[0] == pytest.approx(0.0)


def test_split_exports_continuous_alpha158_price_input(tmp_path: Path) -> None:
    days = [date(2026, 7, 15), date(2026, 7, 16), date(2026, 7, 17)]
    rows = [
        _row("AAPL.US", days[0], 100.0, 0.5),
        _row("AAPL.US", days[1], 100.0, 0.5),
        _row("AAPL.US", days[2], 50.0, 1.0),
    ]
    frame = DailyBarLoader(BarRepository(rows)).load(
        "US", {"AAPL.US"}, days[0], days[-1], "forward_adjusted"
    ).frame
    exporter = object.__new__(QlibDatasetExporter)
    with patch.object(QlibDatasetExporter, "_custom_features", return_value=pd.DataFrame()):
        exporter._write_qlib(tmp_path, frame, {"AAPL.US"}, None, {})

    close_input = np.fromfile(
        tmp_path / "features" / "aapl.us" / "close.day.bin", dtype="<f4"
    )
    assert close_input.tolist() == pytest.approx([0.0, 50.0, 50.0, 50.0])


def test_missing_factor_fails_loader_exporter_and_daily_research() -> None:
    day = date(2026, 7, 17)
    rows = [_row("AAPL.US", day, 100.0, None)]
    repository = BarRepository(rows)
    with pytest.raises(AdjustmentFactorMissingError, match=r"market=US code=AAPL\.US.*2026-07-17.*missing_rows=1"):
        DailyBarLoader(repository).load("US", {"AAPL.US"}, day, day, "forward_adjusted")

    repository.get_universe = lambda _key: SimpleNamespace(
        id=1,
        key="us_sp500",
        market="US",
        enabled=True,
        benchmark_code="QQQ.US",
    )
    repository.active_members = lambda _id, _day: [
        (
            SimpleNamespace(sector_key="technology", sector_benchmark_code="SOXX.US"),
            SimpleNamespace(id=1, code="AAPL.US"),
        )
    ]
    repository.create_dataset = MagicMock()

    with pytest.raises(AdjustmentFactorMissingError, match="AAPL.US"):
        QlibDatasetExporter(repository=repository, artifact_store=MagicMock()).export(
            "US", "us_sp500", day, day
        )
    repository.create_dataset.assert_not_called()
    with pytest.raises(AdjustmentFactorMissingError, match="AAPL.US"):
        DailyResearchService(repository).run("US", "us_sp500", day)


class ExportRepository(BarRepository):
    def __init__(self, rows: list[dict]):
        super().__init__(rows)
        self.snapshots: dict[int, SimpleNamespace] = {}
        self.next_id = 1

    def get_universe(self, _key):
        return SimpleNamespace(
            id=1,
            key="us_sp500",
            market="US",
            enabled=True,
            benchmark_code="QQQ.US",
        )

    def active_members(self, _id, _day):
        return [
            (
                SimpleNamespace(sector_key="technology", sector_benchmark_code="SOXX.US"),
                SimpleNamespace(id=1, code="AAPL.US"),
            )
        ]

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


def test_factor_revision_changes_dataset_key_and_exported_prices(tmp_path: Path) -> None:
    day = date(2026, 7, 17)
    codes = ("AAPL.US", "QQQ.US", "SPY.US", "SOXX.US")
    repository = ExportRepository([_row(code, day, 100.0, 0.5) for code in codes])
    exporter = QlibDatasetExporter(repository, ArtifactStore(tmp_path))
    with patch.object(QlibDatasetExporter, "_custom_features", return_value=pd.DataFrame()):
        first = exporter.export("US", "us_sp500", day, day)
        first_manifest = json.loads(
            (tmp_path / first.artifact_uri.removeprefix("quant://") / "manifest.json").read_text()
        )
        daily = pd.read_csv(tmp_path / first.artifact_uri.removeprefix("quant://") / "source" / "daily.csv")
        repository.rows = [_row(code, day, 100.0, 0.4) for code in codes]
        second = exporter.export("US", "us_sp500", day, day)

    assert first.source_revision != second.source_revision
    assert first.dataset_key != second.dataset_key
    assert first_manifest["price_mode"] == "forward_adjusted"
    assert first_manifest["adjustment_mode"] == "forward"
    assert first_manifest["adjustment_coverage"]["coverage_ratio"] == 1.0
    assert set(daily["close"]) == {50.0}
    assert set(daily["volume"]) == {100.0}
    factor_bin = np.fromfile(
        tmp_path / first.artifact_uri.removeprefix("quant://") / "features" / "aapl.us" / "factor.day.bin",
        dtype="<f4",
    )
    assert factor_bin.tolist() == pytest.approx([0.0, 0.5])


def test_production_training_requires_forward_adjusted_mode() -> None:
    repository = MagicMock()
    repository.get_model_run.return_value = SimpleNamespace(
        id=5, market="US", universe_id=1, dataset_snapshot_id=2
    )
    repository.get_universe.return_value = SimpleNamespace(
        id=1, key="us_sp500", market="US", enabled=True
    )
    repository.get_dataset.return_value = SimpleNamespace(
        id=2,
        market="US",
        universe_id=1,
        status="ready",
        artifact_uri="quant://datasets/raw",
        price_mode="raw",
    )
    with pytest.raises(QuantDatasetMissingError, match="forward_adjusted.*raw"):
        QuantTrainingPipeline(repository, artifact_store=MagicMock()).prepare(5)


def test_quant_dataset_task_explicitly_builds_forward_adjusted_snapshot() -> None:
    snapshot = SimpleNamespace(
        id=7,
        dataset_key="adjusted-dataset",
        status="ready",
        price_mode="forward_adjusted",
        row_count=100,
        symbol_count=4,
    )
    with (
        patch.object(dataset_tasks, "FixedUniverseService") as universe_service_class,
        patch.object(dataset_tasks, "QlibDatasetExporter") as exporter_class,
    ):
        exporter_class.return_value.export.return_value = snapshot
        result = dataset_tasks.build_quant_dataset.run(
            market="US",
            universe="us_sp500",
            date_from="2025-01-01",
            date_to="2026-01-01",
        )

    assert exporter_class.return_value.export.call_args.kwargs["price_mode"] == "forward_adjusted"
    universe_service_class.return_value.refresh.assert_called_once_with("US", date(2026, 1, 1))
    assert result["price_mode"] == "forward_adjusted"
