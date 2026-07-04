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
    if calendar.empty:
        return []
    splits: list[dict] = []
    train_end_index = (
        int(calendar.searchsorted(calendar[0] + pd.DateOffset(years=config.train_years), side="right")) - 1
    )
    gap = config.prediction_horizon + config.embargo_days
    while 0 <= train_end_index < len(calendar) - 1:
        valid_start_index = train_end_index + gap + 1
        if valid_start_index >= len(calendar):
            break
        valid_end_index = min(
            int(
                calendar.searchsorted(
                    calendar[valid_start_index] + pd.DateOffset(months=config.valid_months),
                    side="left",
                )
            )
            - 1,
            len(calendar) - 1,
        )
        test_start_index = valid_end_index + gap + 1
        if test_start_index >= len(calendar):
            break
        test_end_index = min(
            int(
                calendar.searchsorted(
                    calendar[test_start_index] + pd.DateOffset(months=config.test_months),
                    side="left",
                )
            )
            - 1,
            len(calendar) - 1,
        )
        splits.append(
            {
                "train": (calendar[0].date(), calendar[train_end_index].date()),
                "valid": (calendar[valid_start_index].date(), calendar[valid_end_index].date()),
                "test": (calendar[test_start_index].date(), calendar[test_end_index].date()),
                "purge_days": config.prediction_horizon,
                "embargo_days": config.embargo_days,
            }
        )
        next_end = calendar[train_end_index] + pd.DateOffset(months=config.retrain_frequency_months)
        train_end_index = max(
            train_end_index + 1,
            int(calendar.searchsorted(next_end, side="left")),
        )
    return splits
