from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from qlib_worker.protocol import DailyPredictPayload
from qlib_worker.tasks import predict as predict_tasks


def test_daily_predict_loads_alpha158_features_once(monkeypatch) -> None:
    calls: list[str] = []
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2026-07-16"), "A.US"), (pd.Timestamp("2026-07-16"), "B.US")],
        names=["datetime", "instrument"],
    )
    features = pd.DataFrame({"ROC5": [0.1, 0.2], "MA5": [1.0, 1.1]}, index=index)

    monkeypatch.setattr(predict_tasks, "ArtifactStore", lambda _root: SimpleNamespace(path_for_uri=lambda uri: uri))
    monkeypatch.setattr(predict_tasks, "get_worker_config", lambda: SimpleNamespace(artifact_root="unused"))
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
