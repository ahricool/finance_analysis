from __future__ import annotations

from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from qlib_worker.models.base import BaseLGBMRunner


class TimeSeriesLGBMRunner(BaseLGBMRunner):
    """Directional classifier using momentum/volatility features only."""

    name = "time_series_lgbm"
    version = "1"
    model_class = lgb.LGBMClassifier
    default_parameters: dict[str, Any] = {
        **BaseLGBMRunner.default_parameters,
        "class_weight": "balanced",
    }
    allowed_parameters = BaseLGBMRunner.allowed_parameters | {"class_weight"}

    def select_features(self, frame: pd.DataFrame) -> list[str]:
        tokens = ("ROC", "MA", "RSV", "STD", "BETA", "CORR")
        columns = [column for column in frame.columns if column != "label" and any(token in column for token in tokens)]
        if not columns:
            raise ValueError("No time-series momentum/volatility features are available")
        return columns

    def training_target(self, target: pd.Series) -> pd.Series:
        return (target > 0).astype(int)

    def predict(self, model: Any, frame: pd.DataFrame, columns: list[str], medians: pd.Series) -> np.ndarray:
        return np.asarray(model.predict_proba(frame[columns].fillna(medians))[:, 1], dtype=float)

    def normalized_score(self, raw: pd.Series) -> pd.Series:
        return raw
