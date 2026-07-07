"""Model runner interface and shared LightGBM mechanics."""

from __future__ import annotations

from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd


class BaseLGBMRunner:
    name = "base"
    version = "1"
    model_class = lgb.LGBMRegressor
    default_parameters: dict[str, Any] = {
        "n_estimators": 300,
        "learning_rate": 0.03,
        "num_leaves": 31,
        "verbosity": -1,
        "random_state": 42,
        "n_jobs": 1,
    }
    allowed_parameters = {
        "n_estimators",
        "learning_rate",
        "num_leaves",
        "max_depth",
        "min_child_samples",
        "subsample",
        "colsample_bytree",
        "reg_alpha",
        "reg_lambda",
        "random_state",
    }

    def validate_parameters(self, raw: dict[str, Any]) -> dict[str, Any]:
        unknown = sorted(set(raw) - self.allowed_parameters)
        if unknown:
            raise ValueError(f"Unsupported {self.name} parameters: {unknown}")
        return {**self.default_parameters, **raw, "n_jobs": 1, "verbosity": -1}

    def select_features(self, frame: pd.DataFrame) -> list[str]:
        return [column for column in frame.columns if column != "label"]

    def fit(
        self,
        train: pd.DataFrame,
        valid: pd.DataFrame,
        columns: list[str],
        parameters: dict[str, Any],
    ) -> tuple[Any, pd.Series]:
        medians = train[columns].median().fillna(0.0)
        model = self.model_class(**parameters)
        fit_kwargs: dict[str, Any] = {}
        if not valid.empty:
            fit_kwargs = {
                "eval_set": [(valid[columns].fillna(medians), self.training_target(valid["label"]))],
                "callbacks": [lgb.early_stopping(30, verbose=False)],
            }
        model.fit(train[columns].fillna(medians), self.training_target(train["label"]), **fit_kwargs)
        return model, medians

    def training_target(self, target: pd.Series) -> pd.Series:
        return target

    def predict(self, model: Any, frame: pd.DataFrame, columns: list[str], medians: pd.Series) -> np.ndarray:
        return np.asarray(model.predict(frame[columns].fillna(medians)), dtype=float)

    def normalized_score(self, raw: pd.Series) -> pd.Series:
        return raw.rank(pct=True)
