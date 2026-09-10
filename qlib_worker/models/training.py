"""Walk-forward training and final train+valid model construction."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from qlib_worker.models.base import BaseLGBMRunner
from qlib_worker.models.metrics import (
    CLASSIFICATION_PRIMARY_METRICS,
    CROSS_SECTION_PRIMARY_METRICS,
    classification_metrics,
    cross_section_metrics,
    cross_section_trading_metrics,
)
from qlib_worker.models.splits import WalkForwardConfig, serializable_split, walk_forward_splits


def train_walk_forward(
    panel: pd.DataFrame,
    runner: BaseLGBMRunner,
    raw_parameters: dict[str, Any],
    split_config: WalkForwardConfig,
    output: Path,
    bundle_metadata: dict[str, Any],
) -> dict[str, Any]:
    dates = panel.index.get_level_values("datetime").unique()
    folds = walk_forward_splits(dates, split_config)
    if not folds:
        raise ValueError("Dataset is too short for configured walk-forward folds")
    parameters = runner.validate_parameters(raw_parameters)
    columns = runner.select_features(panel)
    fold_results: list[dict[str, Any]] = []
    predictions: list[pd.DataFrame] = []
    fold_best_iterations: list[int | None] = []
    warnings: list[str] = []
    last_model: Any = None
    last_medians: pd.Series | None = None
    last_fold: dict[str, Any] | None = None
    for fold in folds:
        train = _slice(panel, fold["train"]).dropna(subset=["label"])
        valid = _slice(panel, fold["valid"]).dropna(subset=["label"])
        test = _slice(panel, fold["test"]).dropna(subset=["label"])
        if train.empty or valid.empty or test.empty:
            raise ValueError(f"Fold {fold['fold']} has an empty train, valid, or test segment")
        model, medians = runner.fit(train, valid, columns, parameters)
        raw = runner.predict(model, test, columns, medians)
        prediction = pd.DataFrame({"prediction": raw, "label": test["label"]}, index=test.index)
        metrics, fold_warnings = evaluate_predictions(runner, prediction)
        best_iteration = _best_iteration(model)
        fold_results.append(
            {
                "split": serializable_split(fold),
                "metrics": metrics,
                "best_iteration": best_iteration,
                "warnings": fold_warnings,
            }
        )
        prediction["fold"] = fold["fold"]
        predictions.append(prediction)
        fold_best_iterations.append(best_iteration)
        warnings.extend(f"fold {fold['fold']}: {note}" for note in fold_warnings)
        last_model, last_medians, last_fold = model, medians, fold
    assert last_model is not None and last_medians is not None and last_fold is not None
    final_n_estimators = _final_n_estimators(fold_best_iterations, int(parameters["n_estimators"]))
    final_parameters = {**parameters, "n_estimators": final_n_estimators}
    final_end = last_fold["valid"][1]
    final_frame = panel[
        (panel.index.get_level_values("datetime") >= last_fold["train"][0])
        & (panel.index.get_level_values("datetime") <= final_end)
    ].dropna(subset=["label"])
    final_model, final_medians = runner.fit(final_frame, pd.DataFrame(), columns, final_parameters)
    combined_predictions = pd.concat(predictions).sort_index()
    aggregate = _aggregate_metrics(fold_results)
    if runner.task_type != "classification":
        aggregate.update(cross_section_trading_metrics(combined_predictions))
    metrics_payload = {
        **aggregate,
        "task_type": runner.task_type,
        "primary_metrics": list(
            CLASSIFICATION_PRIMARY_METRICS if runner.task_type == "classification" else CROSS_SECTION_PRIMARY_METRICS
        ),
        "folds": fold_results,
        "fold_count": len(fold_results),
        "fold_best_iterations": fold_best_iterations,
        "final_n_estimators": final_n_estimators,
    }
    bundle = {
        "model": final_model,
        "medians": final_medians,
        "columns": columns,
        "final_n_estimators": final_n_estimators,
        "fold_best_iterations": fold_best_iterations,
        **bundle_metadata,
    }
    joblib.dump(bundle, output / "model.joblib")
    combined_predictions.to_parquet(output / "test_predictions.parquet")
    _write_json(output / "metrics.json", metrics_payload)
    importance = dict(
        sorted(
            zip(columns, map(float, final_model.feature_importances_)),
            key=lambda item: item[1],
            reverse=True,
        )[:100]
    )
    return {
        "metrics": metrics_payload,
        "feature_importance": importance,
        "actual_parameters": parameters,
        "final_n_estimators": final_n_estimators,
        "fold_best_iterations": fold_best_iterations,
        "final_training_strategy": "retrain_on_last_fold_train_plus_valid",
        "final_training_end": str(final_end.date()),
        "split_config": asdict(split_config),
        "warnings": warnings,
    }


def evaluate_predictions(runner: BaseLGBMRunner, prediction: pd.DataFrame) -> tuple[dict[str, Any], list[str]]:
    if runner.task_type == "classification":
        return classification_metrics(prediction)
    return cross_section_metrics(prediction), []


def _best_iteration(model: Any) -> int | None:
    value = getattr(model, "best_iteration_", None)
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _final_n_estimators(fold_best_iterations: list[int | None], fallback: int) -> int:
    finite = [int(value) for value in fold_best_iterations if value is not None and int(value) > 0]
    if not finite:
        return max(1, int(fallback))
    return max(1, int(round(float(np.median(finite)))))


def _slice(panel: pd.DataFrame, bounds: tuple[pd.Timestamp, pd.Timestamp]) -> pd.DataFrame:
    dates = panel.index.get_level_values("datetime")
    return panel[(dates >= bounds[0]) & (dates <= bounds[1])]


def _aggregate_metrics(folds: list[dict[str, Any]]) -> dict[str, Any]:
    names = sorted({name for fold in folds for name in fold["metrics"]})
    result: dict[str, Any] = {}
    for name in names:
        values = [fold["metrics"].get(name) for fold in folds]
        finite = [float(value) for value in values if value is not None and np.isfinite(value)]
        result[name] = float(np.mean(finite)) if finite else None
        result[f"{name}_std"] = float(np.std(finite)) if finite else None
    return result


def _write_json(path: Path, payload: Any) -> None:
    import json

    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
