from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qlib_worker.tasks.predict import predict_model
from qlib_worker.tasks.train import train_model


def _dataset(root: Path, periods: int = 650) -> str:
    relative = Path("datasets/minimal-integration")
    dataset = root / relative
    dates = pd.bdate_range("2023-01-03", periods=periods)
    for directory in ("calendars", "instruments", "features", "source"):
        (dataset / directory).mkdir(parents=True, exist_ok=True)
    (dataset / "calendars" / "day.txt").write_text("\n".join(map(str, dates.date)) + "\n", encoding="utf-8")
    instruments: list[str] = []
    source_rows: list[dict[str, object]] = []
    codes = (("A.US", 0.04), ("B.US", 0.06), ("C.US", 0.08), ("QQQ.US", 0.05))
    for offset, (code, drift) in enumerate(codes):
        instruments.append(f"{code}\t{dates[0].date()}\t{dates[-1].date()}")
        feature_directory = dataset / "features" / code.lower()
        feature_directory.mkdir()
        wave = np.sin(np.arange(periods) / (11.0 + offset))
        close = 80.0 + offset * 7.0 + np.arange(periods) * drift + wave
        values = {
            "open": close - 0.15 + wave * 0.02,
            "high": close + 0.6,
            "low": close - 0.6,
            "close": close,
            "vwap": close + 0.03,
            "volume": 100_000.0 + np.arange(periods) * (10 + offset),
            "factor": np.ones(periods),
        }
        values["amount"] = values["vwap"] * values["volume"]
        for field, data in values.items():
            encoded = np.concatenate((np.array([0], dtype="<f4"), np.asarray(data, dtype="<f4")))
            encoded.tofile(feature_directory / f"{field}.day.bin")
        for index, day in enumerate(dates):
            source_rows.append(
                {
                    "instrument": code,
                    "datetime": day,
                    **{field: float(data[index]) for field, data in values.items()},
                }
            )
    (dataset / "instruments" / "all.txt").write_text("\n".join(instruments) + "\n", encoding="utf-8")
    pd.DataFrame(source_rows).to_csv(dataset / "source" / "daily.csv", index=False)
    (dataset / "manifest.json").write_text(
        json.dumps(
            {
                "dataset_key": "minimal-integration",
                "source_revision": "fixture-revision",
                "price_mode": "forward_adjusted",
                "adjustment_mode": "forward",
                "date_from": str(dates[0].date()),
                "date_to": str(dates[-1].date()),
                "symbols": ["A.US", "B.US", "C.US"],
                "benchmark_codes": ["QQQ.US"],
                "market_benchmark": "QQQ.US",
                "sector_benchmark_mapping": {},
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    return f"quant://{relative.as_posix()}"


def test_train_retry_restart_and_predict(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "quant"
    dataset_uri = _dataset(root)
    monkeypatch.setenv("QUANT_ARTIFACT_ROOT", str(root))
    payload = {
        "schema_version": 1,
        "model_run_id": 101,
        "dataset_uri": dataset_uri,
        "model_key": "cross_section_lgbm",
        "model_version": "integration-v1",
        "parameters": {"n_estimators": 10, "learning_rate": 0.1},
        "feature_config": {"base": "Alpha158"},
        "target_config": {
            "prediction_horizon": 5,
            "benchmark": "market",
            "entry_price": "open",
            "exit_price": "close",
            "excess_return": True,
        },
        "split_config": {
            "train_years": 1,
            "valid_months": 2,
            "test_months": 2,
            "retrain_frequency_months": 12,
            "prediction_horizon": 5,
            "embargo_days": 2,
        },
    }
    trained = train_model.run(**payload)
    retried = train_model.run(**payload)
    assert retried == trained
    assert trained["artifact_uri"] == "quant://models/cross_section_lgbm/integration-v1/101"
    artifact = root / "models/cross_section_lgbm/integration-v1/101"
    assert (artifact / "model.joblib").is_file()
    assert not list(artifact.parent.glob(".101.*"))
    metadata_path = artifact / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    assert metadata["price_mode"] == "forward_adjusted"

    predicted = predict_model.run(
        schema_version=1,
        model_run_id=101,
        artifact_uri=trained["artifact_uri"],
        dataset_uri=dataset_uri,
        trade_date=json.loads((artifact / "metadata.json").read_text())["final_training_end"],
        model_key="cross_section_lgbm",
    )
    assert predicted["model_run_id"] == 101
    assert {item["code"] for item in predicted["predictions"]} >= {"A.US", "B.US", "C.US"}

    metadata["price_mode"] = "raw"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="price_mode mismatch"):
        predict_model.run(
            schema_version=1,
            model_run_id=101,
            artifact_uri=trained["artifact_uri"],
            dataset_uri=dataset_uri,
            trade_date=metadata["final_training_end"],
            model_key="cross_section_lgbm",
        )
