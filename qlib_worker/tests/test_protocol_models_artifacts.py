from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from qlib_worker.artifacts.store import ArtifactStore
from qlib_worker.models.registry import get_runner
from qlib_worker.models.splits import WalkForwardConfig, walk_forward_splits
from qlib_worker.models.targets import TargetConfig, build_target
from qlib_worker.protocol import PredictPayload, TrainPayload


def train_payload(**overrides):
    payload = {
        "schema_version": 1,
        "model_run_id": 42,
        "dataset_uri": "quant://datasets/example",
        "model_key": "cross_section_lgbm",
        "model_version": "v1",
        "parameters": {},
        "feature_config": {},
        "target_config": {},
        "split_config": {},
    }
    payload.update(overrides)
    return payload


def test_task_protocol_accepts_json_payload_and_rejects_unknown_version() -> None:
    parsed = TrainPayload.parse(train_payload())
    assert parsed.model_run_id == 42
    with pytest.raises(ValueError, match="schema_version"):
        TrainPayload.parse(train_payload(schema_version=2))
    with pytest.raises(ValueError, match="schema_version"):
        PredictPayload.parse({"schema_version": 999, "model_run_id": 1})


def test_model_registry_is_closed_and_runners_are_distinct() -> None:
    cross_section = get_runner("cross_section_lgbm")
    time_series = get_runner("time_series_lgbm")
    assert cross_section.name != time_series.name
    assert cross_section.model_class is not time_series.model_class
    with pytest.raises(ValueError, match="Unknown model_key"):
        get_runner("arbitrary.module.callable")
    with pytest.raises(ValueError, match="Unsupported"):
        cross_section.validate_parameters({"arbitrary_parameter": True})


def test_walk_forward_uses_session_purge_and_embargo() -> None:
    dates = pd.bdate_range("2020-01-01", "2023-12-31")
    config = WalkForwardConfig(
        train_years=1,
        valid_months=2,
        test_months=2,
        retrain_frequency_months=3,
        prediction_horizon=5,
        embargo_days=3,
    )
    folds = walk_forward_splits(dates, config)
    assert len(folds) > 1
    for fold in folds:
        train_end = dates.get_loc(fold["train"][1])
        valid_start = dates.get_loc(fold["valid"][0])
        valid_end = dates.get_loc(fold["valid"][1])
        test_start = dates.get_loc(fold["test"][0])
        assert valid_start - train_end - 1 == 8
        assert test_start - valid_end - 1 == 8
        assert fold["train"][1] < fold["valid"][0] < fold["test"][0]


def test_target_config_changes_horizon_benchmark_and_prices(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    (dataset / "source").mkdir(parents=True)
    dates = pd.bdate_range("2025-01-01", periods=10)
    rows = []
    for code, drift in (("A.US", 2.0), ("QQQ.US", 1.0)):
        for index, day in enumerate(dates):
            rows.append(
                {
                    "instrument": code,
                    "datetime": day,
                    "open": 100 + index * drift,
                    "close": 101 + index * drift,
                }
            )
    pd.DataFrame(rows).to_csv(dataset / "source" / "daily.csv", index=False)
    manifest = {
        "benchmark_codes": ["QQQ.US"],
        "market_benchmark": "QQQ.US",
        "sector_benchmark_mapping": {},
    }
    one_day = TargetConfig.parse(
        {
            "prediction_horizon": 1,
            "benchmark": "market",
            "entry_price": "open",
            "exit_price": "close",
            "excess_return": True,
        },
        1,
    )
    three_day = TargetConfig.parse(
        {
            "prediction_horizon": 3,
            "benchmark": "none",
            "entry_price": "close",
            "exit_price": "open",
            "excess_return": False,
        },
        3,
    )
    first = build_target(dataset, manifest, one_day)
    second = build_target(dataset, manifest, three_day)
    assert len(first) != len(second)
    assert first.iloc[0] != second.iloc[0]


def test_target_config_uses_market_neutral_name_and_accepts_legacy_alias() -> None:
    default = TargetConfig.parse({}, 5)
    legacy = TargetConfig.parse({"benchmark": "sector_or_qqq"}, 5)

    assert default.benchmark == "sector_or_market"
    assert legacy.benchmark == "sector_or_qqq"


def test_artifact_store_rejects_traversal_and_commits_atomically(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(ValueError, match="traversal"):
        store.path_for_uri("quant://../../escape", must_exist=False)
    uri = store.model_uri("cross_section_lgbm", "v1", 42)
    writes = 0

    def writer(directory: Path):
        nonlocal writes
        writes += 1
        (directory / "model.joblib").write_bytes(b"model")
        (directory / "metadata.json").write_text("{}")
        (directory / "metrics.json").write_text("{}")
        (directory / "test_predictions.parquet").write_bytes(b"predictions")
        return {"schema_version": 1, "model_run_id": 42, "metrics": {}, "feature_importance": {}}

    first = store.commit_model(uri, "request-digest", writer)
    second = store.commit_model(uri, "request-digest", writer)
    assert writes == 1
    assert first == second
    final = store.path_for_uri(uri)
    assert json.loads((final / "artifact_manifest.json").read_text())["digest"] == first["artifact_digest"]
    assert not list(final.parent.glob(".42.*"))
