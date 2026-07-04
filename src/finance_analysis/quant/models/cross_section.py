"""Ridge/LightGBM cross-sectional baselines for degraded non-Qlib operation."""

from __future__ import annotations

import numpy as np
import pandas as pd


class CrossSectionBaseline:
    def __init__(self, model_type="ridge", parameters=None): self.model_type=model_type; self.parameters=parameters or {}; self.model=None; self.columns=[]
    def fit(self, frame, feature_columns, target="label"):
        clean=frame.dropna(subset=feature_columns+[target]); self.columns=feature_columns
        if self.model_type == "ridge":
            from sklearn.pipeline import make_pipeline
            from sklearn.impute import SimpleImputer
            from sklearn.preprocessing import StandardScaler
            from sklearn.linear_model import Ridge
            self.model=make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(**self.parameters))
        elif self.model_type == "lightgbm":
            from lightgbm import LGBMRegressor
            self.model=LGBMRegressor(verbosity=-1, **self.parameters)
        else: raise ValueError(f"Unsupported model_type: {self.model_type}")
        self.model.fit(clean[feature_columns], clean[target]); return self
    def predict(self, frame):
        result=frame.copy(); result["raw_prediction"]=self.model.predict(result[self.columns]); result["normalized_score"]=result.groupby("date")["raw_prediction"].rank(pct=True)
        result["universe_rank"]=result.groupby("date")["raw_prediction"].rank(method="first",ascending=False).astype(int)
        if "sector_key" in result: result["sector_rank"]=result.groupby(["date","sector_key"])["raw_prediction"].rank(method="first",ascending=False).astype(int)
        result["predicted_return"]=result["raw_prediction"]
        return result
