"""Expanding chronological walk-forward folds with session-based purge/embargo."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

import pandas as pd


@dataclass(frozen=True)
class WalkForwardConfig:
    train_years: int = 3
    valid_months: int = 3
    test_months: int = 3
    retrain_frequency_months: int = 3
    prediction_horizon: int = 5
    embargo_days: int = 2

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "WalkForwardConfig":
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ValueError(f"Unknown split_config parameters: {unknown}")
        config = cls(**{key: int(value) for key, value in raw.items()})
        if min(asdict(config).values()) < 0 or config.train_years < 1:
            raise ValueError("Walk-forward durations must be non-negative and train_years must be positive")
        if config.valid_months < 1 or config.test_months < 1 or config.retrain_frequency_months < 1:
            raise ValueError("valid, test and retrain durations must be positive")
        return config


def walk_forward_splits(dates: Iterable[object], config: WalkForwardConfig) -> list[dict[str, Any]]:
    calendar = pd.DatetimeIndex(sorted(pd.to_datetime(pd.Series(list(dates))).dropna().unique()))
    if calendar.empty:
        return []
    folds: list[dict[str, Any]] = []
    train_start_index = 0
    train_end_index = (
        int(calendar.searchsorted(calendar[0] + pd.DateOffset(years=config.train_years), side="right")) - 1
    )
    gap = config.prediction_horizon + config.embargo_days
    while 0 <= train_end_index < len(calendar) - 1:
        valid_start_index = train_end_index + gap + 1
        if valid_start_index >= len(calendar):
            break
        valid_end_target = calendar[valid_start_index] + pd.DateOffset(months=config.valid_months)
        valid_end_index = min(int(calendar.searchsorted(valid_end_target, side="left")) - 1, len(calendar) - 1)
        test_start_index = valid_end_index + gap + 1
        if test_start_index >= len(calendar):
            break
        test_end_target = calendar[test_start_index] + pd.DateOffset(months=config.test_months)
        test_end_index = min(int(calendar.searchsorted(test_end_target, side="left")) - 1, len(calendar) - 1)
        if valid_end_index < valid_start_index or test_end_index < test_start_index:
            break
        folds.append(
            {
                "fold": len(folds) + 1,
                "train": (calendar[train_start_index], calendar[train_end_index]),
                "valid": (calendar[valid_start_index], calendar[valid_end_index]),
                "test": (calendar[test_start_index], calendar[test_end_index]),
                "purge_sessions": config.prediction_horizon,
                "embargo_sessions": config.embargo_days,
            }
        )
        next_end_target = calendar[train_end_index] + pd.DateOffset(months=config.retrain_frequency_months)
        next_end_index = int(calendar.searchsorted(next_end_target, side="left"))
        if next_end_index <= train_end_index:
            next_end_index = train_end_index + 1
        train_end_index = next_end_index
    return folds


def serializable_split(fold: dict[str, Any]) -> dict[str, Any]:
    return {
        key: ([str(value[0].date()), str(value[1].date())] if key in {"train", "valid", "test"} else value)
        for key, value in fold.items()
    }
