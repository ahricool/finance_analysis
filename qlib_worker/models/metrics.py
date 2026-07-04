"""Serializable model evaluation metrics."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def regression_metrics(prediction: pd.DataFrame) -> dict[str, float | None]:
    clean = prediction.replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        raise ValueError("No finite predictions available for evaluation")
    daily = clean.groupby(level="datetime").apply(
        lambda frame: frame["prediction"].corr(frame["label"], method="spearman"),
        include_groups=False,
    )
    values: dict[str, float | None] = {
        "ic": _finite(clean["prediction"].corr(clean["label"])),
        "rank_ic": _finite(clean["prediction"].corr(clean["label"], method="spearman")),
        "rank_ic_mean": _finite(daily.mean()),
        "icir": _finite(daily.mean() / daily.std()) if daily.std() else None,
        "top5_excess_return_pct": _finite(
            clean.groupby(level="datetime")
            .apply(lambda frame: frame.nlargest(5, "prediction")["label"].mean(), include_groups=False)
            .mean()
        ),
        "top10_excess_return_pct": _finite(
            clean.groupby(level="datetime")
            .apply(lambda frame: frame.nlargest(10, "prediction")["label"].mean(), include_groups=False)
            .mean()
        ),
        "mae": _finite((clean["prediction"] - clean["label"]).abs().mean()),
        "rmse": _finite(np.sqrt(((clean["prediction"] - clean["label"]) ** 2).mean())),
        "hit_rate": _finite(((clean["prediction"] > 0) == (clean["label"] > 0)).mean()),
    }
    return values


def _finite(value: object) -> float | None:
    number = float(value) if value is not None else float("nan")
    return number if math.isfinite(number) else None
