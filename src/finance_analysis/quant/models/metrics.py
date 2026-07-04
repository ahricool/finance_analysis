"""Prediction and portfolio metrics; all return values are JSON-safe."""

from __future__ import annotations

import math
import numpy as np
import pandas as pd


def prediction_metrics(frame: pd.DataFrame) -> dict:
    clean = frame.dropna(subset=["prediction", "label"])
    if clean.empty: return {}
    daily = clean.groupby("date").apply(lambda group: pd.Series({"ic": group.prediction.corr(group.label), "rank_ic": group.prediction.corr(group.label, method="spearman")}), include_groups=False)
    errors = clean.prediction - clean.label
    result = {"ic": float(clean.prediction.corr(clean.label)), "rank_ic": float(clean.prediction.corr(clean.label, method="spearman")),
              "ic_mean": float(daily.ic.mean()), "ic_std": float(daily.ic.std()), "rank_ic_mean": float(daily.rank_ic.mean()),
              "icir": float(daily.ic.mean()/daily.ic.std()) if daily.ic.std() else None,
              "mae": float(errors.abs().mean()), "rmse": float(np.sqrt(np.mean(errors**2))), "hit_rate": float(((clean.prediction>0)==(clean.label>0)).mean())}
    predicted_positive = clean.prediction > 0; actual_positive = clean.label > 0
    result["precision"] = float((predicted_positive & actual_positive).sum()/predicted_positive.sum()) if predicted_positive.sum() else None
    result["recall"] = float((predicted_positive & actual_positive).sum()/actual_positive.sum()) if actual_positive.sum() else None
    return result


def portfolio_metrics(returns: pd.Series, turnover: pd.Series | None = None) -> dict:
    returns = returns.dropna().astype(float)
    if returns.empty: return {}
    equity = (1+returns).cumprod(); drawdown = equity/equity.cummax()-1; annual = equity.iloc[-1]**(252/len(returns))-1
    vol = returns.std(ddof=1)*math.sqrt(252); downside = returns[returns<0].std(ddof=1)*math.sqrt(252)
    return {"annualized_return": float(annual), "volatility": float(vol), "sharpe": float(annual/vol) if vol else None,
            "sortino": float(annual/downside) if downside else None, "maximum_drawdown": float(drawdown.min()),
            "calmar": float(annual/abs(drawdown.min())) if drawdown.min() else None, "turnover": float(turnover.mean()) if turnover is not None else None}
