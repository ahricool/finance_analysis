"""Chronological walk-forward splits with purge and embargo."""

from __future__ import annotations

from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class WalkForwardConfig:
    train_years: int = 3
    valid_months: int = 3
    test_months: int = 3
    retrain_frequency_months: int = 3
    prediction_horizon: int = 5
    embargo_days: int = 2


def walk_forward_splits(dates, config: WalkForwardConfig = WalkForwardConfig()) -> list[dict]:
    calendar = pd.DatetimeIndex(sorted(pd.to_datetime(pd.Series(dates).dropna().unique())))
    if calendar.empty: return []
    splits, train_start = [], calendar[0]
    train_end = train_start + pd.DateOffset(years=config.train_years)
    while train_end < calendar[-1]:
        valid_start = train_end + pd.Timedelta(days=config.prediction_horizon + config.embargo_days)
        valid_end = valid_start + pd.DateOffset(months=config.valid_months)
        test_start = valid_end + pd.Timedelta(days=config.prediction_horizon + config.embargo_days)
        test_end = test_start + pd.DateOffset(months=config.test_months)
        if test_start > calendar[-1]: break
        splits.append({"train": (train_start.date(), train_end.date()), "valid": (valid_start.date(), min(valid_end, calendar[-1]).date()),
                       "test": (test_start.date(), min(test_end, calendar[-1]).date()), "purge_days": config.prediction_horizon, "embargo_days": config.embargo_days})
        train_end += pd.DateOffset(months=config.retrain_frequency_months)
    return splits
