"""Shared-panel Logistic and LightGBM time-series baselines."""

from __future__ import annotations

import numpy as np
import pandas as pd


class TimeSeriesBaseline:
    def __init__(self, model_type: str = "logistic", task_type: str = "classification", parameters: dict | None = None):
        self.model_type, self.task_type, self.parameters = model_type, task_type, parameters or {}; self.model = None; self.columns = []

    def fit(self, frame: pd.DataFrame, feature_columns: list[str], target: str = "label"):
        clean = frame.dropna(subset=feature_columns+[target]); self.columns = feature_columns
        if self.model_type == "logistic":
            from sklearn.linear_model import LogisticRegression
            self.model = LogisticRegression(max_iter=1000, class_weight="balanced", **self.parameters); y = (clean[target] > 0).astype(int)
        elif self.model_type == "lightgbm":
            from lightgbm import LGBMClassifier, LGBMRegressor
            self.model = (LGBMClassifier if self.task_type == "classification" else LGBMRegressor)(verbosity=-1, **self.parameters); y = (clean[target]>0).astype(int) if self.task_type == "classification" else clean[target]
        else: raise ValueError(f"Unsupported model_type: {self.model_type}")
        self.model.fit(clean[feature_columns], y); return self

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        if self.model is None: raise RuntimeError("Model is not fitted")
        result = frame.copy(); valid = result[self.columns].notna().all(axis=1); result["time_series_score"] = np.nan; result["predicted_5d_excess_return"] = np.nan
        if self.task_type == "classification":
            values = self.model.predict_proba(result.loc[valid,self.columns])[:,1]; result.loc[valid,"time_series_score"] = values
        else:
            values = self.model.predict(result.loc[valid,self.columns]); result.loc[valid,"predicted_5d_excess_return"] = values; result.loc[valid,"time_series_score"] = 1/(1+np.exp(-values))
        result["trend_state"] = np.where(result["time_series_score"] >= .55, "bullish", np.where(result["time_series_score"] <= .45, "bearish", "neutral"))
        return result
