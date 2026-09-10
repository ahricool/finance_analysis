"""Serializable model evaluation metrics."""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np
import pandas as pd

PRODUCTION_PREDICTION_HORIZON = 5
CROSS_SECTION_PRIMARY_METRICS = (
    "daily_rank_ic_mean",
    "icir",
    "top5_excess_return_pct",
    "top10_excess_return_pct",
    "rank_ic_positive_day_ratio",
)
CLASSIFICATION_PRIMARY_METRICS = (
    "roc_auc",
    "balanced_accuracy",
    "precision",
    "recall",
    "f1",
    "brier_score",
    "directional_hit_rate",
)


def cross_section_metrics(prediction: pd.DataFrame) -> dict[str, float | None]:
    clean = _finite_frame(prediction)
    daily = clean.groupby(level="datetime").apply(
        lambda frame: frame["prediction"].corr(frame["label"], method="spearman"),
        include_groups=False,
    )
    daily = daily.replace([np.inf, -np.inf], np.nan).dropna()
    top5 = _daily_topk_mean(clean, 5)
    top10 = _daily_topk_mean(clean, 10)
    return {
        "daily_rank_ic_mean": _finite(daily.mean()) if not daily.empty else None,
        "icir": _finite(daily.mean() / daily.std()) if not daily.empty and daily.std() else None,
        "top5_excess_return_pct": _finite(top5.mean()) if not top5.empty else None,
        "top10_excess_return_pct": _finite(top10.mean()) if not top10.empty else None,
        "rank_ic_positive_day_ratio": _finite((daily > 0).mean()) if not daily.empty else None,
        "ic": _finite(clean["prediction"].corr(clean["label"])),
        "rank_ic": _finite(clean["prediction"].corr(clean["label"], method="spearman")),
        "mae": _finite((clean["prediction"] - clean["label"]).abs().mean()),
        "rmse": _finite(np.sqrt(((clean["prediction"] - clean["label"]) ** 2).mean())),
    }


def classification_metrics(prediction: pd.DataFrame) -> tuple[dict[str, float | None], list[str]]:
    clean = _finite_frame(prediction)
    y_true = (clean["label"] > 0).astype(int).to_numpy()
    y_score = np.clip(clean["prediction"].to_numpy(dtype=float), 0.0, 1.0)
    y_pred = (y_score >= 0.5).astype(int)
    notes: list[str] = []
    roc_auc = None
    unique = np.unique(y_true)
    if unique.size < 2:
        notes.append("ROC AUC is undefined because the evaluation set contains a single class")
    else:
        roc_auc = _safe_metric("roc_auc", y_true, y_score, notes)
    return {
        "roc_auc": roc_auc,
        "balanced_accuracy": _safe_metric("balanced_accuracy", y_true, y_pred, notes),
        "precision": _safe_metric("precision", y_true, y_pred, notes),
        "recall": _safe_metric("recall", y_true, y_pred, notes),
        "f1": _safe_metric("f1", y_true, y_pred, notes),
        "brier_score": _finite(np.mean((y_score - y_true) ** 2)),
        "directional_hit_rate": _finite((y_pred == y_true).mean()),
        "positive_rate": _finite(y_true.mean()),
    }, notes


def cross_section_trading_metrics(
    prediction: pd.DataFrame,
    *,
    top_ks: tuple[int, ...] = (5, 10),
) -> dict[str, Any]:
    """Mean overlapping 5-day forward returns of daily TopK, not a portfolio backtest."""
    clean = _finite_frame(prediction)
    payload: dict[str, Any] = {
        "assumptions": {
            "label": "walk_forward_oos_forward_return",
            "label_units": "percentage_points",
            "selection": "daily_topk_by_prediction",
            "weighting": "equal_weight",
            "prediction_horizon": PRODUCTION_PREDICTION_HORIZON,
            "periods_overlap": True,
            "not_a_backtest": True,
        }
    }
    for top_k in top_ks:
        daily = _daily_topk_mean(clean, top_k)
        prefix = f"top{top_k}"
        payload[f"{prefix}_oos_return_pct"] = _finite(daily.mean()) if not daily.empty else None
        payload[f"{prefix}_positive_period_ratio"] = _finite((daily > 0).mean()) if not daily.empty else None
    return payload


def _daily_topk_mean(frame: pd.DataFrame, top_k: int) -> pd.Series:
    return frame.groupby(level="datetime").apply(
        lambda group: group.nlargest(min(top_k, len(group)), "prediction")["label"].mean(),
        include_groups=False,
    )


def _finite_frame(prediction: pd.DataFrame) -> pd.DataFrame:
    clean = prediction.replace([np.inf, -np.inf], np.nan).dropna(subset=["prediction", "label"])
    if clean.empty:
        raise ValueError("No finite predictions available for evaluation")
    return clean


def _safe_metric(name: str, y_true: np.ndarray, y_hat: np.ndarray, notes: list[str]) -> float | None:
    try:
        from sklearn.metrics import balanced_accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
    except ImportError as exc:  # pragma: no cover - worker always installs sklearn
        raise RuntimeError("scikit-learn is required for classification metrics") from exc
    calculators = {
        "roc_auc": lambda: roc_auc_score(y_true, y_hat),
        "balanced_accuracy": lambda: balanced_accuracy_score(y_true, y_hat),
        "precision": lambda: precision_score(y_true, y_hat, zero_division=0),
        "recall": lambda: recall_score(y_true, y_hat, zero_division=0),
        "f1": lambda: f1_score(y_true, y_hat, zero_division=0),
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return _finite(calculators[name]())
        except ValueError as exc:
            notes.append(f"{name} is undefined: {exc}")
            return None


def _finite(value: object) -> float | None:
    number = float(value) if value is not None else float("nan")
    return number if math.isfinite(number) else None
