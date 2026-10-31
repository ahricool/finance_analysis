from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
import fcntl

import pandas as pd
import pytest

from qlib_worker.protocol import DailyPredictPayload
from qlib_worker.tasks import predict as predict_tasks


@pytest.mark.parametrize("temporary", (False, True))
def test_daily_predict_loads_alpha158_features_once(monkeypatch, tmp_path, temporary) -> None:
    calls: list[str] = []
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2026-07-16"), "A.US"), (pd.Timestamp("2026-07-16"), "B.US")],
        names=["datetime", "instrument"],
    )
    features = pd.DataFrame({"ROC5": [0.1, 0.2], "MA5": [1.0, 1.1]}, index=index)

    handoff = tmp_path / "temporary/example"
    if temporary:
        handoff.mkdir(parents=True)
        (handoff / "input.bin").write_bytes(b"frozen input")
    monkeypatch.setattr(predict_tasks, "ArtifactStore", lambda _root: SimpleNamespace(
        path_for_uri=lambda uri: handoff if temporary else uri,
    ))
    monkeypatch.setattr(predict_tasks, "get_worker_config",
                        lambda: SimpleNamespace(artifact_root=tmp_path if temporary else "unused"))
    monkeypatch.setattr(
        predict_tasks,
        "load_manifest",
        lambda _dataset: {
            "symbols": ["A.US", "B.US"],
            "price_mode": "forward_adjusted",
            "date_from": "2026-01-01",
            "date_to": "2026-07-16",
            "benchmark_codes": [],
        },
    )
    monkeypatch.setattr(predict_tasks, "require_forward_adjusted_manifest", lambda manifest: manifest["price_mode"])

    def load_features(_dataset, _manifest, _config):
        if temporary:
            assert _dataset.parent == handoff
            assert (_dataset / "input.bin").read_bytes() == b"frozen input"
        calls.append("load_features")
        return features

    monkeypatch.setattr(predict_tasks, "load_features", load_features)

    def fake_predict_one(_store, spec, _price_mode, rows, trade_date):
        return {
            "schema_version": 1,
            "model_run_id": spec.model_run_id,
            "model_key": spec.model_key,
            "trade_date": trade_date,
            "predictions": [
                {"code": code, "normalized_score": 0.5, "raw_prediction": 0.5}
                for code in rows.index.get_level_values("instrument")
            ],
        }

    monkeypatch.setattr(predict_tasks, "_predict_one", fake_predict_one)

    result = predict_tasks.predict_daily.run(
        schema_version=1,
        dataset_uri="quant://datasets/example",
        trade_date="2026-07-16",
        cross_section={
            "model_run_id": 11,
            "model_key": "cross_section_lgbm",
            "artifact_uri": "quant://models/cs",
        },
        time_series={
            "model_run_id": 12,
            "model_key": "time_series_lgbm",
            "artifact_uri": "quant://models/ts",
        },
    )

    assert calls == ["load_features"]
    assert {item["model_key"] for item in result["results"]} == {"cross_section_lgbm", "time_series_lgbm"}
    assert all(len(item["predictions"]) == 2 for item in result["results"])
    if temporary:
        assert not handoff.exists()


@pytest.mark.parametrize("fail", (False, True))
def test_prediction_context_cleans_owned_files_and_keeps_lease_until_exit(tmp_path, fail):
    handoff = tmp_path / "temporary/run"
    handoff.mkdir(parents=True)
    (handoff / "manifest.json").write_text("{}")
    (handoff / "features").mkdir()
    (handoff / "features/data.bin").write_bytes(b"data")
    working = None
    caught = False
    try:
        with predict_tasks.prediction_input_lease(handoff, tmp_path) as working:
            assert working != handoff
            assert (working / "features/data.bin").read_bytes() == b"data"
            with (handoff / ".lease").open("a") as lease:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if fail:
                raise ValueError("prediction failed")
    except ValueError as exc:
        caught = True
        assert fail and str(exc) == "prediction failed"
    assert caught is fail
    assert working is not None and not working.exists()
    assert not handoff.exists()


def test_prediction_context_preserves_persistent_training_data_on_failure(tmp_path):
    dataset = tmp_path / "datasets/training"
    dataset.mkdir(parents=True)
    (dataset / "manifest.json").write_text("keep")
    with pytest.raises(ValueError, match="failed"):
        with predict_tasks.prediction_input_lease(dataset, tmp_path) as working:
            assert working == dataset
            raise ValueError("failed")
    assert (dataset / "manifest.json").read_text() == "keep"


def test_temporary_named_folder_in_training_tree_is_not_consumed(tmp_path):
    dataset = tmp_path / "datasets/temporary/training"
    dataset.mkdir(parents=True)
    (dataset / "manifest.json").write_text("keep")
    with predict_tasks.prediction_input_lease(dataset, tmp_path) as working:
        assert working == dataset
    assert (dataset / "manifest.json").read_text() == "keep"


def test_partial_input_transfer_is_cleaned_on_failure(tmp_path, monkeypatch):
    handoff = tmp_path / "temporary/run"
    handoff.mkdir(parents=True)
    (handoff / "features").mkdir()
    (handoff / "features/data.bin").write_bytes(b"data")
    (handoff / "manifest.json").write_text("{}")
    original = Path.rename

    def rename(path, target):
        if path.name == "manifest.json":
            raise OSError("transfer failed")
        return original(path, target)

    monkeypatch.setattr(Path, "rename", rename)
    with pytest.raises(OSError, match="transfer failed"):
        with predict_tasks.prediction_input_lease(handoff, tmp_path):
            pytest.fail("Partial handoff must not reach prediction")
    assert not handoff.exists()


def test_consumed_input_is_not_recreated_by_late_delivery(tmp_path):
    handoff = tmp_path / "temporary/run"
    with pytest.raises(FileNotFoundError):
        with predict_tasks.prediction_input_lease(handoff, tmp_path):
            pytest.fail("Missing input must not be recreated")
    assert not handoff.exists()


def test_daily_predict_payload_rejects_swapped_model_keys() -> None:
    with pytest.raises(ValueError, match="time_series.model_key"):
        DailyPredictPayload.parse(
            {
                "schema_version": 1,
                "dataset_uri": "quant://datasets/example",
                "trade_date": "2026-07-16",
                "cross_section": {
                    "model_run_id": 11,
                    "model_key": "cross_section_lgbm",
                    "artifact_uri": "quant://cs",
                },
                "time_series": {
                    "model_run_id": 12,
                    "model_key": "cross_section_lgbm",
                    "artifact_uri": "quant://ts",
                },
            }
        )
